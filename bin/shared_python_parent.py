#!/usr/bin/env python3
"""
Run web, the Celery worker and the Temporal worker as children of one process that imported the app.

Each of the three loads all of Django and most of the same product code. As separate containers
each holds its own copy. This launcher imports everything the three need once, then forks one child
per role. The children share the parent's memory pages until they write to them, and the parent
freezes its objects first so that a child's garbage collection does not write to those pages.

bin/docker-server runs this instead of granian when POSTHOG_SHARED_PYTHON_PARENT=true, so the
container's migration steps and GRANIAN_* defaults still apply. The web role starts granian through
bin/granian_preload.py. The Celery role takes the settings that bin/docker-worker-celery reads
(WEB_CONCURRENCY, CELERY_MAX_TASKS_PER_CHILD, CELERY_MAX_MEMORY_PER_CHILD,
CELERY_WORKER_PREFETCH_MULTIPLIER) and always runs the scheduler inside the worker. Keep its
arguments in sync with that script.

A role that exits is started again from the same parent, so it shares the parent's memory again.
A role that exits soon after it starts cannot run, so the launcher stops the other roles and exits
with an error, and the container's restart policy takes over.

bin/test/test_shared_python_parent.py checks the fork, restart and shutdown behavior on Linux.
"""

import gc
import os
import grp
import pwd
import sys
import time
import atexit
import signal
import tempfile
import importlib
import subprocess
from collections.abc import Callable

APP_TARGET = "posthog.asgi:application"

# The directory that bin/docker-worker-celery gives the Celery worker.
CELERY_PROMETHEUS_DIR = "/tmp/posthog_celery_prometheus"

# Web keeps bin/docker-server's PROMETHEUS_METRICS_EXPORT_PORT. All three roles share one network
# namespace, so the other two need ports of their own.
CELERY_METRICS_PORT = "8002"
TEMPORAL_METRICS_PORT = "8003"

# A role that exits before this many seconds have passed counts as unable to start.
MIN_UPTIME_SECONDS = 60


def log(message: str) -> None:
    sys.stderr.write(f"shared_python_parent: {message}\n")
    sys.stderr.flush()


def drop_privileges() -> None:
    # The same change as `setpriv --reuid=nobody --regid=nogroup --clear-groups` in bin/docker-server.
    if os.geteuid() != 0:
        return
    os.setgroups([])
    os.setgid(grp.getgrnam("nogroup").gr_gid)
    os.setuid(pwd.getpwnam("nobody").pw_uid)


def run_web(prometheus_dir: str | None) -> None:
    import granian_preload

    if prometheus_dir:
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = prometheus_dir
    drop_privileges()
    metrics_server = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "granian_metrics.py")])
    atexit.register(metrics_server.terminate)
    sys.argv = ["granian", APP_TARGET]
    granian_preload.main()


def run_celery() -> None:
    from celery.__main__ import main

    os.environ["CELERY_METRICS_PORT"] = CELERY_METRICS_PORT
    argv = ["celery", "-A", "posthog", "worker", "-Ofair", "-n", "node@%h"]
    argv += ["--beat", "--scheduler", "redbeat.RedBeatScheduler", "--without-mingle", "--without-heartbeat"]
    for flag, setting in (
        ("--concurrency", "WEB_CONCURRENCY"),
        ("--max-tasks-per-child", "CELERY_MAX_TASKS_PER_CHILD"),
        ("--max-memory-per-child", "CELERY_MAX_MEMORY_PER_CHILD"),
        ("--prefetch-multiplier", "CELERY_WORKER_PREFETCH_MULTIPLIER"),
    ):
        if os.environ.get(setting):
            argv += [flag, os.environ[setting]]
    sys.argv = argv
    main()


def run_temporal() -> None:
    from django.core.management import execute_from_command_line

    os.environ["PROMETHEUS_MULTIPROC_DIR"] = tempfile.mkdtemp(prefix="posthog_temporal_prometheus_")
    execute_from_command_line(["manage.py", "start_temporal_worker", "--metrics-port", TEMPORAL_METRICS_PORT])


def import_the_app() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    # bin/docker-worker-celery starts the worker with this value, and Django reads it during the import.
    os.environ["SKIP_ASYNC_MIGRATIONS_SETUP"] = "0"
    # posthog/celery.py reads this during the import and deletes the metric files in that directory
    # when the worker starts, so it must not be the directory that web writes to.
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = CELERY_PROMETHEUS_DIR
    # Running this file puts bin/ on sys.path, not the working directory that holds the app.
    sys.path.insert(0, os.getcwd())

    importlib.import_module(APP_TARGET.split(":")[0])
    from posthog.celery import app

    app.loader.import_default_modules()
    importlib.import_module("posthog.management.commands.start_temporal_worker")

    # A forked child inherits the parent's open sockets. Two processes that use one database
    # connection corrupt its protocol stream, so close any that the import opened.
    from django.db import connections

    connections.close_all()
    # The collection runs first because a frozen garbage cycle is never freed.
    gc.collect()
    gc.freeze()


def supervise(roles: dict[str, Callable[[], None]], min_uptime_seconds: float = MIN_UPTIME_SECONDS) -> int:
    children: dict[int, tuple[str, float]] = {}
    stopping = False

    def start(name: str) -> None:
        pid = os.fork()
        if pid == 0:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.default_int_handler)
            # The role exits the way it does as its own process, so its exit handlers run.
            roles[name]()
            sys.exit(0)
        children[pid] = (name, time.monotonic())
        log(f"started {name} as pid {pid}")

    def stop(signum: int | None = None, frame: object = None) -> None:
        nonlocal stopping
        stopping = True
        for pid in list(children):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for name in roles:
        start(name)

    exit_code = 0
    while children:
        pid, status = os.wait()
        # As PID 1 of a container this process also reaps orphans that are not its roles.
        if pid not in children:
            continue
        name, started_at = children.pop(pid)
        log(f"{name} (pid {pid}) exited with {os.waitstatus_to_exitcode(status)}")
        if stopping:
            continue
        if time.monotonic() - started_at < min_uptime_seconds:
            log(f"{name} exited within {min_uptime_seconds:.0f} seconds of its start, stopping the other roles")
            exit_code = 1
            stop()
        else:
            start(name)
    return exit_code


def main() -> None:
    web_prometheus_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    started_at = time.monotonic()
    import_the_app()
    log(f"imported the app in {time.monotonic() - started_at:.0f} seconds")
    sys.exit(
        supervise(
            {
                "web": lambda: run_web(web_prometheus_dir),
                "celery": run_celery,
                "temporal": run_temporal,
            }
        )
    )


if __name__ == "__main__":
    main()
