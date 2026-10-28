#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import gc
import os
import sys
import json
import math
import time
import faulthandler
from collections.abc import Callable
from pathlib import Path
from threading import Thread

# Add common/ to path so migration_utils module is importable (used by custom migrate command)
_common_path = str(Path(__file__).parent / "common")
if _common_path not in sys.path:
    sys.path.insert(0, _common_path)


def relay_command_diagnostics(read_fd: int, destination_fd: int) -> None:
    try:
        while chunk := os.read(read_fd, 4096):
            while chunk:
                written = os.write(destination_fd, chunk)
                chunk = chunk[written:]
    except OSError:
        pass
    finally:
        os.close(read_fd)
        os.close(destination_fd)


def start_command_diagnostics() -> Callable[[str], None]:
    def disabled(_phase: str) -> None:
        pass

    if os.environ.get("POSTHOG_COMMAND_DIAGNOSTICS") != "1" or sys.stderr is None:
        return disabled
    descriptors: list[int] = []
    try:
        destination_fd = os.dup(sys.stderr.fileno())
        descriptors.append(destination_fd)
        read_fd, write_fd = os.pipe()
        descriptors.extend((read_fd, write_fd))
        os.set_blocking(write_fd, False)
        Thread(target=relay_command_diagnostics, args=(read_fd, destination_fd), daemon=True).start()
    except (OSError, ValueError, RuntimeError):
        for descriptor in descriptors:
            os.close(descriptor)
        return disabled

    def write(message: str) -> None:
        try:
            os.write(write_fd, (message + "\n").encode())
        except OSError:
            pass

    try:
        interval = float(os.environ.get("POSTHOG_COMMAND_DIAGNOSTICS_INTERVAL_SECONDS", "60"))
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError
        faulthandler.dump_traceback_later(interval, repeat=True, exit=False, file=write_fd)
    except (ValueError, OverflowError, OSError, RuntimeError):
        write("Command diagnostics disabled: invalid dump interval or unavailable watchdog.")
        os.close(write_fd)
        return disabled
    started_at = time.monotonic()
    identity = {
        "job": os.environ.get("MIGRATION_JOB_NAME", ""),
        "namespace": os.environ.get("MIGRATION_NAMESPACE", ""),
        "pod": os.environ.get("MIGRATION_POD_NAME", ""),
    }

    def record_phase(phase: str) -> None:
        write(
            json.dumps(
                {
                    "event": "management_command_phase",
                    "phase": phase,
                    "pid": os.getpid(),
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                    **identity,
                }
            )
        )

    record_phase("process_started")
    return record_phase


def main() -> None:
    record_phase = start_command_diagnostics()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    record_phase("django_import_started")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    record_phase("django_import_finished")

    # Boot allocations are almost all permanent (modules, classes, registries), so cyclic GC
    # during django.setup() only adds pauses (~300ms across ~470 collections). Disable it for
    # the boot, then freeze the survivors so later full collections skip them too. Skipped when
    # --settings/--pythonpath override the settings module, since those only take effect inside
    # execute_from_command_line. See docs/internal/django-startup-time.md.
    if not any(arg.startswith(("--settings", "--pythonpath")) for arg in sys.argv):
        gc.disable()
        try:
            import django

            record_phase("django_setup_started")
            django.setup()
            record_phase("django_setup_finished")
        finally:
            gc.freeze()
            gc.enable()

    # Default query tags so management commands don't trip the DEBUG-only UntaggedQueryError
    # in sync_execute. HTTP requests (runserver's CHQueries middleware) and Celery tasks reset
    # tags at their own boundaries, so this only effectively applies to direct CLI commands.
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

    try:
        with tags_context(product=Product.INTERNAL, feature=Feature.MANAGEMENT_COMMAND):
            record_phase("command_started")
            execute_from_command_line(sys.argv)
    finally:
        record_phase("command_finished")


if __name__ == "__main__":
    main()
