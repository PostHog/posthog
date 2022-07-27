#!/usr/bin/env python3
# -*- coding: utf-8 -*-


loglevel = "error"
keepalive = 120
timeout = 90
grateful_timeout = 120


def on_starting(server):
    print(
        """
\x1b[1;34m"""
        + r"""
 _____          _   _    _
|  __ \        | | | |  | |
| |__) |__  ___| |_| |__| | ___   __ _
|  ___/ _ \/ __| __|  __  |/ _ \ / _` |
| |  | (_) \__ \ |_| |  | | (_) | (_| |
|_|   \___/|___/\__|_|  |_|\___/ \__, |
                                  __/ |
                                 |___/
"""
        + """
\x1b[0m
"""
    )
    print("Server running on \x1b[4mhttp://{}:{}\x1b[0m".format(*server.address[0]))
    print("Questions? Please shoot us an email at \x1b[4mhey@posthog.com\x1b[0m")
    print("\nTo stop, press CTRL + C")


def worker_exit(server, worker):
    # Ensure that we mark workers as dead with the prometheus_client such that
    # any cleanup can happen.
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
