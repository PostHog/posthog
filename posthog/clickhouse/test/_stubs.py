"""Shared Django/ClickHouse stubs for standalone migration tool tests.

WHY STUBS INSTEAD OF DJANGO TEST RUNNER:
PostHog's Django startup (posthog/__init__.py, settings, celery) triggers
ClickHouse client connections, Kafka configuration, and celery app setup.
Running these tests via `DJANGO_SETTINGS_MODULE=posthog.settings.test pytest`
requires a full Django environment with live ClickHouse — impractical for
unit tests that only exercise YAML parsing, diff logic, and plan generation.
These stubs isolate the migration_tools package from Django/CH/celery so
tests run fast with zero infrastructure.

Usage at the top of each test file (BEFORE any posthog imports):

    import posthog.clickhouse.test._stubs as _stubs  # noqa: F401

    # _stubs installs itself on import — now posthog.* is safe to import.

Or for standalone execution:

    _BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    sys.path.insert(0, _BASE)
    import posthog.clickhouse.test._stubs  # noqa: F401

This module installs all stubs on import — no need to call install_stubs() explicitly.
The stubs are idempotent and safe to import multiple times.
"""

from __future__ import annotations

import os
import sys
import types

from unittest.mock import MagicMock

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)


def _django_is_configured() -> bool:
    try:
        from django.conf import settings

        val = getattr(settings, "USE_I18N", None)
        return isinstance(val, bool)
    except Exception:
        return False


class _NodeRole:
    DATA = "DATA"
    COORDINATOR = "COORDINATOR"
    ALL = "ALL"

    def __init__(self, value: str = "data") -> None:
        self.value = value


class _FakeQuery:
    def __init__(self, sql: str) -> None:
        self.sql = sql


class _FakeRunPython:
    def __init__(self, fn: object) -> None:
        self.fn = fn


def _fake_get_cluster(*args: object, **kwargs: object) -> MagicMock:
    mock = MagicMock()
    mock.any_host.return_value.result.return_value = {}
    return mock


def _install() -> None:
    if _django_is_configured():
        return

    # posthog package — prevent __init__.py from running
    if "posthog" not in sys.modules:
        pkg = types.ModuleType("posthog")
        pkg.__path__ = [os.path.join(_BASE, "posthog")]
        pkg.__package__ = "posthog"
        pkg.celery_app = None  # type: ignore[attr-defined]
        sys.modules["posthog"] = pkg

    # posthog.celery
    _celery = types.ModuleType("posthog.celery")
    _celery.app = types.SimpleNamespace()  # type: ignore[attr-defined]
    sys.modules.setdefault("posthog.celery", _celery)

    # posthog.clickhouse (package)
    ch_pkg = types.ModuleType("posthog.clickhouse")
    ch_pkg.__path__ = [os.path.join(_BASE, "posthog/clickhouse")]
    ch_pkg.__package__ = "posthog.clickhouse"
    sys.modules.setdefault("posthog.clickhouse", ch_pkg)

    # posthog.clickhouse.client
    fake_client = types.ModuleType("posthog.clickhouse.client")
    fake_client.__path__ = [os.path.join(_BASE, "posthog/clickhouse/client")]
    fake_client.__package__ = "posthog.clickhouse.client"
    sys.modules.setdefault("posthog.clickhouse.client", fake_client)

    # posthog.clickhouse.client.connection
    fake_conn = types.ModuleType("posthog.clickhouse.client.connection")
    fake_conn.NodeRole = _NodeRole  # type: ignore[attr-defined]
    sys.modules.setdefault("posthog.clickhouse.client.connection", fake_conn)

    # posthog.clickhouse.cluster
    fake_cluster = types.ModuleType("posthog.clickhouse.cluster")
    fake_cluster.Query = _FakeQuery  # type: ignore[attr-defined]
    fake_cluster.get_cluster = _fake_get_cluster  # type: ignore[attr-defined]
    fake_cluster.ClickhouseCluster = MagicMock  # type: ignore[attr-defined]

    # HostInfo is a NamedTuple used by schema_introspect — provide a lightweight stand-in
    from collections import namedtuple as _nt

    fake_cluster.HostInfo = _nt(  # type: ignore[attr-defined]
        "HostInfo",
        ["connection_info", "shard_num", "replica_num", "host_cluster_type", "host_cluster_role"],
    )
    sys.modules.setdefault("posthog.clickhouse.cluster", fake_cluster)

    # infi.clickhouse_orm
    for mod_name in ("infi", "infi.clickhouse_orm"):
        m = types.ModuleType(mod_name)
        m.__path__ = ["/fake"]
        sys.modules.setdefault(mod_name, m)

    infi_migrations = types.ModuleType("infi.clickhouse_orm.migrations")
    infi_migrations.__path__ = ["/fake"]
    infi_migrations.RunPython = _FakeRunPython  # type: ignore[attr-defined]
    sys.modules.setdefault("infi.clickhouse_orm.migrations", infi_migrations)

    # posthog.settings
    fake_settings = types.ModuleType("posthog.settings")
    fake_settings.E2E_TESTING = False  # type: ignore[attr-defined]
    fake_settings.DEBUG = True  # type: ignore[attr-defined]
    fake_settings.CLOUD_DEPLOYMENT = False  # type: ignore[attr-defined]
    sys.modules.setdefault("posthog.settings", fake_settings)

    fake_ds = types.ModuleType("posthog.settings.data_stores")
    fake_ds.CLICKHOUSE_MIGRATIONS_CLUSTER = "default"  # type: ignore[attr-defined]
    fake_ds.CLICKHOUSE_MIGRATIONS_HOST = "localhost"  # type: ignore[attr-defined]
    sys.modules.setdefault("posthog.settings.data_stores", fake_ds)

    # posthog.clickhouse.client.migration_tools
    fake_mt = types.ModuleType("posthog.clickhouse.client.migration_tools")
    fake_mt.get_migrations_cluster = _fake_get_cluster  # type: ignore[attr-defined]
    sys.modules.setdefault("posthog.clickhouse.client.migration_tools", fake_mt)

    # posthog.clickhouse.migration_tools.cluster_registry — let real module load
    # (its only dependency is posthog.clickhouse.cluster which is already stubbed above)

    # yaml (for manifest.py)

    _yaml_stub = types.ModuleType("yaml")
    try:
        import yaml as _real_yaml

        _yaml_stub.safe_load = _real_yaml.safe_load  # type: ignore[attr-defined]
        _yaml_stub.dump = _real_yaml.dump  # type: ignore[attr-defined]
    except ImportError:
        _yaml_stub.safe_load = lambda f: None  # type: ignore[attr-defined]
        _yaml_stub.dump = lambda *a, **kw: None  # type: ignore[attr-defined]
    sys.modules.setdefault("yaml", _yaml_stub)

    # posthog.clickhouse.test (package)
    test_pkg = types.ModuleType("posthog.clickhouse.test")
    test_pkg.__path__ = [os.path.join(_BASE, "posthog/clickhouse/test")]
    test_pkg.__package__ = "posthog.clickhouse.test"
    sys.modules.setdefault("posthog.clickhouse.test", test_pkg)

    # django stubs (for ch_migrate command tests)
    for mod_name in ("django", "django.conf", "django.core", "django.core.management", "django.core.management.base"):
        m = types.ModuleType(mod_name)
        m.__path__ = ["/fake"]
        sys.modules.setdefault(mod_name, m)

    if not hasattr(sys.modules.get("django.conf"), "settings"):
        settings_ns = types.SimpleNamespace(
            CLICKHOUSE_DATABASE="default",
            CLICKHOUSE_HOST="localhost",
            CLICKHOUSE_CLUSTER="posthog",
            CLICKHOUSE_LOGS_CLUSTER_HOST="localhost",
            CLICKHOUSE_LOGS_CLUSTER="posthog_single_shard",
            CLICKHOUSE_MIGRATIONS_HOST="localhost",
            CLICKHOUSE_MIGRATIONS_CLUSTER="posthog_migrations",
        )
        sys.modules["django.conf"].settings = settings_ns  # type: ignore[attr-defined]

    class _FakeBaseCommand:
        def __init__(self) -> None:
            self.stdout = __import__("io").StringIO()
            self.stderr = __import__("io").StringIO()

        def print_help(self, *args: object) -> None:
            pass

    if not hasattr(sys.modules.get("django.core.management.base"), "BaseCommand"):
        sys.modules["django.core.management.base"].BaseCommand = _FakeBaseCommand  # type: ignore[attr-defined]

    # Wire submodule attributes so `from posthog import settings` works
    sys.modules["posthog"].settings = sys.modules["posthog.settings"]  # type: ignore[attr-defined]
    sys.modules["posthog.settings"].data_stores = sys.modules["posthog.settings.data_stores"]  # type: ignore[attr-defined]

    # posthog.management.commands — make it a resolvable package
    for mod_name in ("posthog.management", "posthog.management.commands"):
        if mod_name not in sys.modules:
            m = types.ModuleType(mod_name)
            m.__path__ = [os.path.join(_BASE, mod_name.replace(".", "/"))]
            m.__package__ = mod_name
            sys.modules[mod_name] = m


_install()
