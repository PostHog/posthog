#!/usr/bin/env python3
"""
Run the granian CLI with worker processes started by fork.

Python 3.14 changed the default multiprocessing start method on Linux from fork to
forkserver. Granian does not use forkserver, so it falls back to spawn. A spawned
worker runs full interpreter finalization when it stops, while granian's Rust threads
can still attach to the interpreter. That race aborts the worker with
"Fatal Python error: PyGILState_Release" and similar messages. A forked worker runs
its atexit handlers and then ends with os._exit, without finalization, which is how
granian workers stopped on Python 3.13.

bin/docker-server runs this instead of `granian`. Every GRANIAN_* setting still applies.
"""

import multiprocessing

import granian.cli


def main() -> None:
    multiprocessing.set_start_method("fork")
    granian.cli.entrypoint()


if __name__ == "__main__":
    main()
