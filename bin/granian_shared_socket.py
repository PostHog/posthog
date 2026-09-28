#!/usr/bin/env python3
"""
Run the granian CLI with one listen socket shared by all workers.

Since granian 2.8, each worker on Linux gets its own SO_REUSEPORT socket, and the
kernel hashes every new connection to one of them without looking at load. A pool
that runs one request per worker (backpressure 1) then queues connections behind a
busy worker while other workers idle. With one shared socket all workers take from
a single accept queue, so only a free worker picks up the next connection. That is
how granian 2.7 works on Linux, and how 2.8 still works on macOS, Windows and Unix
domain sockets.

This uses granian's private server API. bin/test/test_granian_shared_socket.py
checks the behaviour on Linux, so a granian upgrade that breaks it fails CI.

bin/docker-server runs this instead of `granian` when
POSTHOG_GRANIAN_SHARED_SOCKET=true. Every GRANIAN_* setting still applies.
"""

import socket

import granian.cli
from granian.net import SocketSpec
from granian.server import MPServer


class SharedSocketServer(MPServer):
    def _init_shared_socket(self) -> None:
        """
        The non-Linux TCP branch of AbstractServer._init_shared_socket, plus the
        inheritable socket that MPServer hands to its workers.
        """
        if self.bind_uds:
            super()._init_shared_socket()
            return
        self._ssp = SocketSpec(self.bind_addr, self.bind_port, self.backlog)
        self._shd = self._ssp.build()
        self._sfd = self._shd.get_fd()
        self._ssp = None
        self._sso = socket.socket(fileno=self._sfd)
        self._sso.set_inheritable(True)


def main() -> None:
    # Fail at boot, not silently, if granian stops building its servers this way.
    if granian.cli.Server is not MPServer or not hasattr(MPServer, "_init_shared_socket"):
        raise RuntimeError("granian internals changed, the shared socket override no longer applies")
    granian.cli.Server = SharedSocketServer
    granian.cli.entrypoint()


if __name__ == "__main__":
    main()
