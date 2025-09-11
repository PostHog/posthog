#!/usr/bin/env python3

import os
import sys
import time
import socket
import struct
import logging
import threading

import structlog
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
            "gunicorn_active_worker_connections",
            "Number of active connections.",
            labelnames=["pid"],
        )
        max_worker_connections = Gauge(
            "gunicorn_max_worker_connections",
            "Maximum worker connections.",
            labelnames=["pid"],
        )

        total_threads = Gauge(
            "gunicorn_max_worker_threads",
            "Size of the thread pool per worker.",
            labelnames=["pid"],
        )
        active_threads = Gauge(
            "gunicorn_active_worker_threads",
            "Number of threads actively processing requests.",
            labelnames=["pid"],
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


LOGGING_FORMATTER_NAME = os.getenv("LOGGING_FORMATTER_NAME", "default")


# Setup stdlib logging to be handled by Structlog
def add_pid_and_tid(
    logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    event_dict["pid"] = os.getpid()
    event_dict["tid"] = threading.get_ident()
    return event_dict


pre_chain = [
    # Add the log level and a timestamp to the event_dict if the log entry
    # is not from structlog.
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    add_pid_and_tid,
    structlog.processors.TimeStamper(fmt="iso"),
]


# This is a copy the default logging config for gunicorn but with additions to:
#
#  1. non propagate loggers to the root handlers (otherwise we get duplicate log
#     lines)
#  2. use structlog for processing of log records
#
# See
# https://github.com/benoitc/gunicorn/blob/0b953b803786997d633d66c0f7c7b290df75e07c/gunicorn/glogging.py#L48
# for the default log settings.
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "default": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.dev.ConsoleRenderer(colors=True),
            "foreign_pre_chain": pre_chain,
        },
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
            "foreign_pre_chain": pre_chain,
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "gunicorn.error": {
            "level": "INFO",
            "handlers": ["error_console"],
            "propagate": False,
            "qualname": "gunicorn.error",
        },
        "gunicorn.access": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
            "qualname": "gunicorn.access",
        },
    },
    "handlers": {
        "error_console": {
            "class": "logging.StreamHandler",
            "formatter": LOGGING_FORMATTER_NAME,
            "stream": "ext://sys.stderr",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOGGING_FORMATTER_NAME,
            "stream": "ext://sys.stdout",
        },
    },
}
