from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.db import connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.test.testcases import LiveServerThread, _StaticFilesHandler

from .ports import DJANGO_LIVE_PORT

logger = logging.getLogger(__name__)


class EvalLiveServer:
    """In-process Django HTTP server on the test database, for the eval session.

    Replaces pytest-django's ``LiveServer`` helper with a session-lifetime
    ``LiveServerThread`` (not per-test). The sandbox Docker container reaches
    this server via ``host.docker.internal`` for API requests, log persistence,
    and the LLM gateway.
    """

    def __init__(self, port: int = DJANGO_LIVE_PORT) -> None:
        # If using in-memory sqlite databases, hand the connections to the server
        # thread so it shares the same database. Postgres needs nothing here, but
        # keep the logic so the helper matches pytest-django's behavior.
        connections_override: dict[str, BaseDatabaseWrapper] = {}
        for conn in connections.all():
            if conn.vendor == "sqlite" and conn.is_in_memory_db():
                connections_override[conn.alias] = conn

        static_handler = (
            StaticFilesHandler if "django.contrib.staticfiles" in settings.INSTALLED_APPS else _StaticFilesHandler
        )

        # Bind on all interfaces so the sandbox Docker container can reach the server
        # via ``host.docker.internal`` (the docker bridge gateway). The socket binds
        # at thread start using this host; we then re-point ``thread.host`` at
        # localhost purely so ``url`` advertises a loopback address to host-side
        # clients (MCP server, LLM gateway) — the already-bound 0.0.0.0 socket still
        # accepts both loopback and bridge connections.
        self.thread = LiveServerThread(
            "0.0.0.0",
            static_handler=static_handler,
            connections_override=connections_override,
            port=port,
        )
        self.thread.daemon = True

        for conn in connections_override.values():
            conn.inc_thread_sharing()

        self.thread.start()
        self.thread.is_ready.wait()
        if self.thread.error:
            error = self.thread.error
            self.stop()
            raise error

        self.thread.host = "127.0.0.1"
        logger.info("Django live server started at %s (bound on 0.0.0.0)", self.url)

    @property
    def url(self) -> str:
        return f"http://{self.thread.host}:{self.thread.port}"

    def __str__(self) -> str:
        return self.url

    def stop(self) -> None:
        self.thread.terminate()
        for conn in self.thread.connections_override.values():
            conn.dec_thread_sharing()
        logger.info("Django live server stopped")
