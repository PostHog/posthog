#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import socket
import struct
import sys
import threading
import time

from prometheus_client import CollectorRegistry, Gauge, multiprocess, start_http_server

loglevel = "error"
keepalive = 120

# Set the timeout to something lower than any downstreams, such that if the
# timeout is hit, then the worker will be killed and respawned, which will then
# we able to pick up any connections that were previously pending on the socket
# and serve the requests before the downstream timeout.
timeout = 15

grateful_timeout = 120


METRICS_UPDATE_INTERVAL_SECONDS = int(os.getenv("GUNICORN_METRICS_UPDATE_SECONDS", 5))


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

    # Start a thread in the Arbiter that will monitor the backlog on the sockets
    # Gunicorn is listening on.
    socket_monitor = SocketMonitor(server=server, registry=registry)
    socket_monitor.start()


def post_fork(server, worker):
    """
    Within each worker process, start a thread that will monitor the thread and
    connection pool.
    """
    worker_monitor = WorkerMonitor(worker=worker)
    worker_monitor.start()


def worker_exit(server, worker):
    """
    Ensure that we mark workers as dead with the prometheus_client such that
    any cleanup can happen.
    """
    multiprocess.mark_process_dead(worker.pid)


class SocketMonitor(threading.Thread):
    """
    We have enabled the statsd collector for Gunicorn, but this doesn't include
    the backlog due to concerns over portability, see
    https://github.com/benoitc/gunicorn/pull/2407

    Instead, we expose to Prometheus a gauge that will report the backlog size.

    We can then:

     1. use this to monitor how well the Gunicorn instances are keeping up with
        requests.
     2. use this metric to handle HPA scaling e.g. in Kubernetes

    """

    def __init__(self, server, registry):
        super().__init__()
        self.daemon = True
        self.server = server
        self.registry = registry

    def run(self):
        """
        Every X seconds, check to see how many connections are pending for each
        server socket.

        We label each individually, as limits such as `--backlog` will apply to
        each individually.
        """
        if sys.platform != "linux":
            # We use the assumption that we are on Linux to be able to get the
            # socket backlog, so if we're not on Linux, we return immediately.
            return

        backlog_gauge = Gauge(
            "gunicorn_pending_connections",
            "The number of pending connections on all sockets. Linux only.",
            registry=self.registry,
            labelnames=["listener"],
        )

        while True:
            for sock in self.server.LISTENERS:
                backlog = self.get_backlog(sock=sock)
                backlog_gauge.labels(listener=str(sock)).set(backlog)

            time.sleep(METRICS_UPDATE_INTERVAL_SECONDS)

    def get_backlog(self, sock):
        # tcp_info struct from include/uapi/linux/tcp.h
        fmt = "B" * 8 + "I" * 24
        tcp_info_struct = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 104)
        # 12 is tcpi_unacked
        return struct.unpack(fmt, tcp_info_struct)[12]


class WorkerMonitor(threading.Thread):
    """
    There is a statsd logger support in Gunicorn that allows us to gather
    metrics e.g. on the number of workers, requests, request duration etc. See
    https://docs.gunicorn.org/en/stable/instrumentation.html for details.

    To get a better understanding of the pool utilization, number of accepted
    connections, we start a thread in head worker to report these via prometheus
    metrics.
    """

    def __init__(self, worker):
        super().__init__()
        self.daemon = True
        self.worker = worker

    def run(self):
        """
        Every X seconds, check the status of the Thread pool, as well as the
        """
        active_worker_connections = Gauge(
            "gunicorn_active_worker_connections", "Number of active connections.", labelnames=["pid"]
        )
        max_worker_connections = Gauge(
            "gunicorn_max_worker_connections", "Maximum worker connections.", labelnames=["pid"]
        )

        total_threads = Gauge("gunicorn_max_worker_threads", "Size of the thread pool per worker.", labelnames=["pid"])
        active_threads = Gauge(
            "gunicorn_active_worker_threads", "Number of threads actively processing requests.", labelnames=["pid"]
        )

        pending_requests = Gauge(
            "gunicorn_pending_requests",
            "Number of requests that have been read from a connection but have not completed yet",
            labelnames=["pid"],
        )

        max_worker_connections.labels(pid=self.worker.pid).set(self.worker.cfg.worker_connections)
        total_threads.labels(pid=self.worker.pid).set(self.worker.cfg.threads)

        while True:
            active_worker_connections.labels(pid=self.worker.pid).set(self.worker.nr_conns)
            active_threads.labels(pid=self.worker.pid).set(min(self.worker.cfg.threads, len(self.worker.futures)))
            pending_requests.labels(pid=self.worker.pid).set(len(self.worker.futures))

            time.sleep(METRICS_UPDATE_INTERVAL_SECONDS)
