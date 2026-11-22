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
import sys
import time
import signal
import tempfile
import importlib
import traceback
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

# After a stop, the launcher sends SIGTERM again to the roles that remain on this interval, because
# a worker can lose the first one while it starts up. This is the interval that
# bin/temporal-django-worker uses.
STOP_RESEND_SECONDS = 30
# The launcher then kills the roles that remain. The Temporal worker waits up to 5 minutes for its
# activities to finish (DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT in posthog/temporal/common/shutdown.py),
# so this is longer than that. A Celery task that is still running at this point is lost.
STOP_GRACE_SECONDS = 330


def log(message: str) -> None:
    sys.stderr.write(f"shared_python_parent: {message}\n")
    sys.stderr.flush()


def run_web(prometheus_dir: str | None) -> None:
    import granian_preload

    if prometheus_dir:
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = prometheus_dir
    metrics_server = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "granian_metrics.py")])
    try:
        sys.argv = ["granian", APP_TARGET]
        granian_preload.main()
    finally:
        metrics_server.terminate()


def run_celery() -> None:
    from celery.__main__ import main

    from posthog.async_migrations.setup import setup_async_migrations

    # Django skips this in the parent's ready() by default, which keeps web and Temporal as they
    # were in their own containers. bin/docker-worker-celery turns it on for the worker only.
    setup_async_migrations()
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


def run_role(role: Callable[[], None]) -> int:
    code = 0
    try:
        role()
    except SystemExit as exit_request:
        if isinstance(exit_request.code, int):
            code = exit_request.code
        elif exit_request.code is not None:
            code = 1
    except BaseException:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    # The caller ends the process with os._exit, as multiprocessing does for the children that
    # granian and Celery fork. A normal exit runs the exit handlers that the parent's imports
    # registered. Those handlers wait on threads that exist only in the parent, so the role never exits.
    return code


def supervise(
    roles: dict[str, Callable[[], None]],
    min_uptime_seconds: float = MIN_UPTIME_SECONDS,
    stop_resend_seconds: float = STOP_RESEND_SECONDS,
    stop_grace_seconds: float = STOP_GRACE_SECONDS,
) -> int:
    children: dict[int, tuple[str, float]] = {}
    stopping = False
    stopped_at = 0.0
    last_term_at = 0.0
    stop_signals = {signal.SIGTERM, signal.SIGINT}

    def start(name: str) -> None:
        # A stop signal that arrives between the fork and the bookkeeping would leave a child
        # that nobody signals, so the signals wait until both are done.
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, stop_signals)
        try:
            if stopping:
                return
            pid = os.fork()
            if pid == 0:
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                signal.signal(signal.SIGINT, signal.default_int_handler)
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
                os._exit(run_role(roles[name]))
            children[pid] = (name, time.monotonic())
            log(f"started {name} as pid {pid}")
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    def send(signum: int) -> None:
        for pid in list(children):
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                pass

    def stop(signum: int | None = None, frame: object = None) -> None:
        nonlocal stopping, stopped_at, last_term_at
        if not stopping:
            stopped_at = last_term_at = time.monotonic()
        stopping = True
        send(signal.SIGTERM)

    def escalate() -> None:
        nonlocal last_term_at
        now = time.monotonic()
        if now - stopped_at >= stop_grace_seconds:
            log(f"{len(children)} roles are still running after {stop_grace_seconds:.0f} seconds, killing them")
            send(signal.SIGKILL)
        elif now - last_term_at >= stop_resend_seconds:
            last_term_at = now
            send(signal.SIGTERM)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for name in roles:
        start(name)

    exit_code = 0
    while children:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if pid == 0:
            if stopping:
                escalate()
            time.sleep(0.1)
            continue
        # When this process is PID 1 of its container, orphaned descendants are reparented to it.
        # Reaping them here keeps them from staying as zombies.
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
    if os.environ.get("GRANIAN_INTERFACE", "asgi") != "asgi":
        log("the web role runs the ASGI app, so GRANIAN_INTERFACE must be asgi")
        sys.exit(2)
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
