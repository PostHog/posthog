import os
import sys
import json
import math
import time
import faulthandler
from collections.abc import Callable
from threading import Thread


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

    if sys.stderr is None:
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
