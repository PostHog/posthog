#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from prometheus_client import CollectorRegistry, multiprocess, start_http_server

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


def when_ready(server):
    """
    To ease being able to hide the /metrics endpoint when running in production,
    we serve the metrics on a separate port, using the
    prometheus_client.multiprocess Collector to pull in data from the worker
    processes.
    """
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    port = int(os.environ.get("PROMETHEUS_METRICS_EXPORT_PORT", 8001))
    start_http_server(port=port, registry=registry)


def worker_exit(server, worker):
    """
    Ensure that we mark workers as dead with the prometheus_client such that
    any cleanup can happen.
    """
    multiprocess.mark_process_dead(worker.pid)
