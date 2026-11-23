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

A fork copies only the thread that calls fork(). A lock that another thread held at that
moment stays locked in the child, and a library whose thread pool started in the parent
waits for threads that the child does not have. A polars call in a forked worker hangs
this way. A socket open in the parent is shared by every worker, and two processes that
use one connection corrupt its protocol stream. So after the import the launcher closes
the database and Redis connections, and it forks only when the parent has one thread and
no stream socket that the import opened. Otherwise it starts again without the preload and logs
why. The preload then saves no memory, but no worker can hang or share a connection.
QUIET_LIBRARY_THREADS stops some libraries that the app imports from starting threads, and
DEFERRED_LIBRARIES delays the others until a worker uses them.
Granian starts its own threads in the parent after the first worker, to wait for each
worker. Those threads hold no locks while they wait, and granian forked its workers with
them on Linux by default before Python 3.14.

bin/docker-server runs this instead of `granian` when POSTHOG_GRANIAN_PRELOAD=true.
Every GRANIAN_* setting still applies. With POSTHOG_GRANIAN_SHARED_SOCKET=true the workers
also share one listen socket, see bin/granian_shared_socket.py. bin/test/test_granian_preload.py
checks on Linux that ASGI workers run the app the parent imported, that WSGI workers import
their own, that the shared socket applies in both cases, and that the launcher does not fork
after an import that leaves a thread or a stream socket. A granian upgrade that breaks this
fails CI.
"""

import os
import sys
import types
import socket
import importlib
import threading
import importlib.util
import multiprocessing

import granian.cli
from granian_shared_socket import use_shared_socket

# The values that granian's click options read as true.
TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}

# Set when the parent was not safe to fork, so that the new launcher process skips the preload.
NOT_SAFE_TO_FORK = "POSTHOG_GRANIAN_PRELOAD_NOT_SAFE"

# Libraries read these settings when they load. Each setting stops one library from starting
# threads in the parent during the import. An operator can still set another value, and the
# launcher then runs without the preload.
QUIET_LIBRARY_THREADS = {
    # OpenBLAS, which numpy loads, starts one thread for each CPU.
    "OPENBLAS_NUM_THREADS": "1",
    # polars and pyarrow each contain a jemalloc that starts threads to return free memory to the system.
    "_RJEM_MALLOC_CONF": "background_thread:false",
    "JE_ARROW_MALLOC_CONF": "background_thread:false",
}


def load_duckdb() -> types.ModuleType:
    import duckdb  # noqa: PLC0415

    return duckdb


def load_polars() -> types.ModuleType:
    import polars  # noqa: PLC0415

    return polars


# Libraries that start threads when they load, and that no setting stops. The app imports them
# at boot through code that it runs only for some requests. The parent gets a stand-in module,
# and each worker loads the library when it first uses it.
DEFERRED_LIBRARIES = {"duckdb": load_duckdb, "polars": load_polars}

# Reentrant, because one library can use another deferred library while it loads.
_deferred_load_lock = threading.RLock()


class DeferredModule(types.ModuleType):
    """
    Stands in for a library in sys.modules until code reads an attribute that the stand-in does not have.

    The import system reads __spec__ from a module in sys.modules, so the stand-in has a real one.
    importlib.util.LazyLoader loads the library on that read, so it cannot keep a library out of the parent.
    """

    def __getattr__(self, attr: str):
        with _deferred_load_lock:
            if sys.modules.get(self.__name__) is self:
                del sys.modules[self.__name__]
            library = DEFERRED_LIBRARIES[self.__name__]()
        return getattr(library, attr)


def defer_libraries() -> None:
    for name in DEFERRED_LIBRARIES:
        spec = importlib.util.find_spec(name)
        if spec is None or name in sys.modules:
            continue
        module = DeferredModule(name)
        module.__spec__ = spec
        sys.modules[name] = module


def env(name: str) -> str:
    # Granian parses these values without regard to case or surrounding spaces.
    return os.environ.get(name, "").strip().lower()


def why_not_preload() -> str | None:
    if env("GRANIAN_INTERFACE") != "asgi" or env("GRANIAN_RELOAD") in TRUE_VALUES:
        return "needs GRANIAN_INTERFACE=asgi without reload"
    if sys.platform != "linux":
        return "can check the parent only on Linux"
    return os.environ.get(NOT_SAFE_TO_FORK) or None


def open_stream_sockets() -> set[str]:
    """
    Return the stream sockets that this process has open, by their /proc inode name.

    Processes that share a stream socket mix their bytes in one stream. A datagram socket sends each
    message whole and keeps no connection state, so the workers can share one. The statsd client
    opens such a socket when the app loads.
    """
    sockets = set()
    for fd in os.listdir("/proc/self/fd"):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            # The directory listing itself used an fd that is closed now.
            continue
        if not target.startswith("socket:"):
            continue
        with socket.socket(fileno=os.dup(int(fd))) as sock:
            if sock.type == socket.SOCK_STREAM:
                sockets.add(target)
    return sockets


def why_not_safe_to_fork(sockets_before_import: set[str]) -> str | None:
    threads = len(os.listdir("/proc/self/task"))
    if threads > 1:
        return f"the app import left {threads - 1} threads running beside the main thread"
    opened = open_stream_sockets() - sockets_before_import
    if opened:
        return f"the app import left {len(opened)} stream sockets open"
    return None


def run_again_without_preload(reason: str) -> None:
    sys.stderr.write(f"granian_preload: {reason}, so each worker imports the app itself\n")
    os.environ[NOT_SAFE_TO_FORK] = reason
    # A new process, because this one already holds the app that the workers would not use.
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), *sys.argv[1:]])


def main() -> None:
    # The same test as bin/docker-server, which accepts only the exact value.
    if os.environ.get("POSTHOG_GRANIAN_SHARED_SOCKET") == "true":
        use_shared_socket()

    if reason := why_not_preload():
        if not os.environ.get(NOT_SAFE_TO_FORK):
            sys.stderr.write(f"granian_preload: {reason}, so not preloading\n")
        granian.cli.entrypoint()
        return

    for name, value in QUIET_LIBRARY_THREADS.items():
        os.environ.setdefault(name, value)
    defer_libraries()
    sockets_before_import = open_stream_sockets()

    target = sys.argv[-1]
    # The granian CLI puts the working directory on sys.path itself. This import runs first.
    sys.path.insert(0, os.getcwd())
    importlib.import_module(target.split(":")[0])

    # Close the connections that the import opened, so that no worker inherits a socket
    # that another process also uses.
    django_db = sys.modules.get("django.db")
    if django_db is not None:
        django_db.connections.close_all()
    posthog_redis = sys.modules.get("posthog.redis")
    if posthog_redis is not None:
        posthog_redis.disconnect_clients()

    if reason := why_not_safe_to_fork(sockets_before_import):
        run_again_without_preload(reason)

    multiprocessing.set_start_method("fork", force=True)
    granian.cli.entrypoint()


if __name__ == "__main__":
    main()
