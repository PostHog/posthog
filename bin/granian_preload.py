#!/usr/bin/env python3
"""
Run the granian CLI with the app imported once, in the parent, before the workers start.

On Python 3.14 granian starts each worker with multiprocessing "spawn", so every worker
imports Django on its own and shares no memory with the others. This launcher imports the
app module in the parent and switches multiprocessing to "fork". The workers then start
with the app already loaded, and they share its memory pages with the parent until they
write to them. posthog/asgi.py and posthog/wsgi.py call gc.freeze() at the end of the
import, so the workers' garbage collection does not write to those pages.

bin/docker-server runs this instead of `granian` when POSTHOG_GRANIAN_PRELOAD=true.
Every GRANIAN_* setting still applies. bin/test/test_granian_preload.py checks on Linux
that the workers run the app the parent imported, so a granian upgrade that breaks this
fails CI.
"""

import os
import sys
import importlib
import multiprocessing

import granian.cli


def main() -> None:
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
