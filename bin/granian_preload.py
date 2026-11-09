#!/usr/bin/env python3
"""
Run the granian CLI with the app imported once, in the parent, before the workers start.

On Python 3.14 granian starts each worker with multiprocessing "spawn", so every worker
imports Django on its own and shares no memory with the others. This launcher imports the
app module in the parent and switches multiprocessing to "fork". The workers then start
with the app already loaded, and they share its memory pages with the parent until they
write to them. posthog/asgi.py calls gc.freeze() at the end of the import, so the workers'
garbage collection does not write to those pages.

Only the ASGI interface without reload is preloaded. posthog/wsgi.py starts the OTel and
profiler threads during the import, and a forked worker gets those threads in a dead state.
In reload mode granian replaces the workers when a file changes, and a forked worker would
keep the code that the parent imported at start. In both cases the launcher runs granian
as `granian` would, and each worker imports the app itself.

bin/docker-server runs this instead of `granian` when POSTHOG_GRANIAN_PRELOAD=true.
Every GRANIAN_* setting still applies. bin/test/test_granian_preload.py checks on Linux
that ASGI workers run the app the parent imported and that WSGI workers import their own,
so a granian upgrade that breaks this fails CI.
"""

import os
import sys
import importlib
import multiprocessing

import granian.cli

# The values that granian's click options read as true.
TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}


def env(name: str) -> str:
    # Granian parses these values without regard to case or surrounding spaces.
    return os.environ.get(name, "").strip().lower()


def can_preload() -> bool:
    return env("GRANIAN_INTERFACE") == "asgi" and env("GRANIAN_RELOAD") not in TRUE_VALUES


def main() -> None:
    if not can_preload():
        sys.stderr.write("granian_preload: needs GRANIAN_INTERFACE=asgi without reload, so not preloading\n")
        granian.cli.entrypoint()
        return

    target = sys.argv[-1]
    # The granian CLI puts the working directory on sys.path itself. This import runs first.
    sys.path.insert(0, os.getcwd())
    importlib.import_module(target.split(":")[0])

    # A forked worker inherits the parent's open sockets. Two processes that use one
    # database connection corrupt its protocol stream, so close any that the import opened.
    django_db = sys.modules.get("django.db")
    if django_db is not None:
        django_db.connections.close_all()

    multiprocessing.set_start_method("fork", force=True)
    granian.cli.entrypoint()


if __name__ == "__main__":
    main()
