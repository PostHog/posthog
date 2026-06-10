import sys
import subprocess
from pathlib import Path

# Heavy subsystems that must NOT be imported by a bare ``django.setup()``. Each one was
# deliberately pulled off the startup path (lazy API router, deferred AI-core imports,
# deferred embedded-ClickHouse). Importing any of them at setup means a new module-level
# import re-opened a door — defer it (function-local / TYPE_CHECKING / lazy facade) instead
# of widening this budget. See logs/startup-profile and the PRs that introduced these cuts.
FORBIDDEN_AT_SETUP = [
    "posthog.api.rest_router",  # the 160-route DRF aggregator — builds lazily on first request
    "posthog.temporal.ai",  # AI temporal workflows -> ee.hogai chat-agent core
    "ee.hogai.chat_agent.graph",  # the assistant graph
    "ee.hogai.tools",  # the agent tool registry
    "chdb",  # embedded ClickHouse
    "posthog.temporal.ai_observability",  # eval/clustering workers (pulls scipy, etc.)
    "scipy",  # only reached via ai_observability clustering — must not be at startup
    "posthog.session_recordings.session_recording_api",  # pulls the session_summary workflow
    "google.genai",  # Gemini SDK — only reached via the session-summary video workflow
    "mimesis",  # fake-data generator — only used by demo-data tasks
    "stripe",  # Stripe SDK — only on the billing/agentic-provisioning request path (deferred there)
    "dagster",  # orchestration framework — only the dagster worker needs it (cluster.py logger is lazy)
    "dlt",  # data-load-tool — only the warehouse import pipelines need it (deferred in pipeline typings)
    "products.revenue_analytics.backend.views.sources.stripe",  # revenue view builders (pandas-heavy)
    "user_agents",  # UA parser — only the request-time UA-summary path needs it (deferred in posthog.utils)
    "products.batch_exports.backend.temporal",  # batch export workflows + every destination's vendor SDK
    "databricks",  # Databricks SDK — only the databricks batch export destination needs it
    "snowflake",  # Snowflake SDK — only the snowflake batch export destination needs it
]

# Runs in a clean interpreter: pytest has already imported half the world, so we cannot
# inspect this process's sys.modules. A subprocess gives a faithful cold-start snapshot.
_SNAPSHOT = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
import sys
print("\\n".join(sorted(m for m in sys.modules)))
"""


def test_django_setup_does_not_import_heavy_subsystems() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _SNAPSHOT],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"django.setup() failed:\n{result.stderr[-2000:]}"
    loaded = set(result.stdout.splitlines())

    offenders = [mod for mod in FORBIDDEN_AT_SETUP if mod in loaded or any(m.startswith(mod + ".") for m in loaded)]
    assert not offenders, (
        f"These heavy modules were imported by a bare django.setup(): {offenders}. "
        "Something added a module-level import that drags them onto the startup path "
        "(shell, migrate, celery, CI all pay for it). Defer the offending import instead."
    )


# Counterpart guard to the lazy API router: with the route aggregator off the startup path,
# a model class only registers if its app's ``models/__init__`` imports it (importing the
# class is what runs ``ModelBase.__new__`` -> ``apps.register_model``). A model reachable
# *only* through a viewset import would silently vanish from ``apps.get_models()`` at
# setup-time, breaking makemigrations, admin, and the django-stubs mypy plugin. This asserts
# every model registers at app-population, so importing the router adds none.
_ROUTER_MODEL_DIFF = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
from django.apps import apps

def labels():
    return {f"{m._meta.app_label}.{m.__name__}" for m in apps.get_models()}

before = labels()
from posthog.api import rest_router  # noqa: F401 — building the aggregator imports ~200 viewsets
after = labels()
print("\\n".join(sorted(after - before)))
"""


def test_all_models_register_at_app_population_not_via_router() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _ROUTER_MODEL_DIFF],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"snapshot failed:\n{result.stderr[-2000:]}"
    late = [m for m in result.stdout.splitlines() if m]
    assert not late, (
        f"These models only registered once the API router imported their viewsets: {late}. "
        "A model must be imported from its app's models/__init__ (or models.py) so it registers "
        "at app-population — Django requires this for makemigrations, admin, and mypy. Add the "
        "missing import to the app's models package instead of relying on a viewset import."
    )


# Same trap as the model guard, but for Django signal receivers. Importing a viewset module also runs
# its ``@receiver`` decorators — so the eager router connected a pile of receivers as a side effect of
# ``django.setup()``. With the lazy router those connect only when the router is first built, so any
# process that never builds it (celery, temporal, migrate, shell) silently loses them. The fallout is
# not cosmetic: feature-flag cache invalidation (``flags_cache``/``local_evaluation``) and alert
# cleanup (``alerts.backend.api.alert``) stop firing on background writes. Every receiver must be wired
# at setup — canonically from the owning app's ``AppConfig.ready()`` — so building the router connects
# none. The offending receivers are now wired from their owning ``AppConfig.ready()`` (feature_flags,
# alerts, ee, and posthog core); this guards against new viewset-only receivers sneaking back in.
_ROUTER_RECEIVER_DIFF = """
import os
import weakref

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django

django.setup()
from django.db.models import signals
from posthog.models.signals import model_activity_signal

_SIGNALS = ["pre_save", "post_save", "pre_delete", "post_delete", "m2m_changed", "pre_init", "post_init"]
# model_activity_signal is PostHog's custom audit-log signal, not a django.db.models one. Its
# `handle_*_change` receivers live in viewset modules, so they are exactly the kind that the eager
# router used to wire as a side effect — include it or this whole class of regression is invisible.
_CUSTOM_SIGNALS = {"model_activity": model_activity_signal}


def _resolve(entry):
    ref = entry[1]
    fn = ref() if isinstance(ref, weakref.ReferenceType) else ref
    if fn is None:
        return None
    return f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', repr(fn))}"


def _connected():
    out = set()
    for name in _SIGNALS:
        for entry in getattr(signals, name).receivers:
            resolved = _resolve(entry)
            if resolved:
                out.add(f"{name}:{resolved}")
    for name, sig in _CUSTOM_SIGNALS.items():
        for entry in sig.receivers:
            resolved = _resolve(entry)
            if resolved:
                out.add(f"{name}:{resolved}")
    return out


before = _connected()
from posthog.api import rest_router  # noqa: F401 — building the aggregator imports ~200 viewsets
after = _connected()
print("\\n".join(sorted(after - before)))
"""


def test_signal_receivers_connect_at_setup_not_via_router() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _ROUTER_RECEIVER_DIFF],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"snapshot failed:\n{result.stderr[-2000:]}"
    late = [r for r in result.stdout.splitlines() if r]
    assert not late, (
        f"These {len(late)} signal receivers connect ONLY when the API router is imported: {late}. "
        "They are wired as an import side effect of a viewset module, so with the lazy router they never "
        "connect in a process that doesn't build it (celery, temporal, migrate, shell). Connect them from "
        "the owning app's AppConfig.ready() so they wire at django.setup()."
    )


# The diff guard above has a blind spot: it only catches a receiver that connects *late* (via the
# router). It cannot catch a receiver that connects in NO process — e.g. someone deletes an
# F401-suppressed side-effect import from an AppConfig.ready(), so the handler is never imported, never
# wired, and `before`/`after` both lack it (empty diff, green test) while the audit log silently stops.
# This positive check pins the receivers this refactor relocated into a ready(): each must be present in
# the setup-time snapshot, so dropping its wiring fails loudly. One representative receiver per relocated
# ready() import — when adding a new ready()-wired receiver, add it here too.
_RELOCATED_RECEIVERS = [
    # Audit-log handlers (model_activity_signal) extracted into light activity_logging modules or wired
    # from a viewset import at ready(), because the lazy router no longer drags them in.
    "products.feature_flags.backend.activity_logging.handle_feature_flag_change",
    "products.dashboards.backend.activity_logging.handle_dashboard_change",
    "products.dashboards.backend.activity_logging.handle_dashboard_widget_change",
    "products.data_warehouse.backend.activity_logging.handle_external_data_source_change",
    "products.data_warehouse.backend.activity_logging.handle_external_data_schema_change",
    "products.ai_observability.backend.activity_logging.handle_evaluation_change",
    "products.batch_exports.backend.activity_logging.handle_batch_export_change",
    "products.managed_migrations.backend.api.batch_imports.handle_batch_import_change",
    "products.actions.backend.api.action.handle_action_change",
    "products.annotations.backend.api.annotation.handle_annotation_change",
    "products.alerts.backend.api.alert.handle_alert_configuration_change",
    "products.logs.backend.alerts_api.handle_logs_alert_activity",
    "products.logs.backend.sampling_api.handle_logs_sampling_rule_activity",
    "posthog.api.tagged_item.handle_tag_change",
    "posthog.api.tagged_item.handle_tagged_item_change",
    # Cache-invalidation receivers wired from products/feature_flags AppConfig.ready().
    "products.feature_flags.backend.flags_cache.feature_flag_changed_flags_cache",
    "products.feature_flags.backend.local_evaluation.feature_flag_changed",
]

# Reuses _connected() from the diff snapshot, but prints the SETUP-TIME set (before the router builds) so
# the test can assert the relocated receivers are present there.
_SETUP_RECEIVER_SNAPSHOT = _ROUTER_RECEIVER_DIFF.replace(
    """before = _connected()
from posthog.api import rest_router  # noqa: F401 — building the aggregator imports ~200 viewsets
after = _connected()
print("\\n".join(sorted(after - before)))""",
    """print("\\n".join(sorted(_connected())))""",
)


def test_relocated_receivers_present_at_setup() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _SETUP_RECEIVER_SNAPSHOT],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"snapshot failed:\n{result.stderr[-2000:]}"
    # Strip the "signal:" prefix — we only care that each handler is connected to *some* signal at setup.
    connected = {line.split(":", 1)[1] for line in result.stdout.splitlines() if ":" in line}
    missing = [r for r in _RELOCATED_RECEIVERS if r not in connected]
    assert not missing, (
        f"These receivers were relocated into an AppConfig.ready() but are NOT connected at django.setup(): "
        f"{missing}. Their ready() import was likely dropped (e.g. a 'remove unused import' cleanup deleted a "
        "# noqa: F401 side-effect import), so they wire in no process and their audit/cache writes silently "
        "stop. Restore the ready() import in the owning app, or update _RELOCATED_RECEIVERS if intentional."
    )


# Cold-start trap the lazy router introduced and the whole pytest suite is blind to. With the AI agent
# core off the startup path, a fresh process no longer pre-imports it — so the FIRST reader of the MCP
# tool registry (the first MCP-tools API request in a new worker) becomes the first importer of the
# ee.hogai.tools -> chat_agent chain. A latent cycle in that chain (.task -> core.executor ->
# posthog.temporal.ai -> chat_agent.toolkit -> back into ee.hogai.tools) used to resolve only by
# import-order luck: the eager router imported the chain at setup, so by the time anything read the
# registry the modules were already complete. Remove that luck and the first request 500s on a
# half-initialized import. Every in-process test misses it because hundreds of test modules import the
# agent core long before the registry is read, so the cycle is always pre-resolved. A clean interpreter
# is the only place this reproduces — same reason the snapshot guards above run in a subprocess.
_MCP_REGISTRY_COLD_LOAD = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
from ee.hogai.mcp_tool import mcp_tool_registry
names = mcp_tool_registry.get_names()
assert names, "registry returned no tools"
print(len(names))
"""


def test_mcp_tool_registry_loads_cold_without_import_cycle() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _MCP_REGISTRY_COLD_LOAD],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "Reading the MCP tool registry in a cold process (mirrors the first MCP-tools request in a fresh "
        "worker) crashed. A module-level import in a tool submodule reaches back into ee.hogai.tools through "
        "the chat_agent chain, forming a cycle that only resolves when something imported the agent core "
        f"first — which no longer happens at django.setup(). Defer the offending import. Subprocess stderr:\n"
        f"{result.stderr[-2000:]}"
    )


# The boot entrypoints (manage.py, wsgi.py, asgi.py) disable cyclic GC around django.setup()
# and freeze the survivors — boot allocations are ~all permanent, so collecting them only adds
# pauses (~300ms). The dangerous failure mode is the window not closing: GC left disabled means
# unbounded cycle growth in a long-lived process. This boots through manage.py and asserts both
# ends of the window.
def test_boot_gc_window_reenables_and_freezes() -> None:
    manage_py = Path(__file__).parents[2] / "manage.py"
    probe = (
        "import gc; "
        "assert gc.isenabled(), 'GC left disabled after boot'; "
        "count = gc.get_freeze_count(); "
        "assert count > 100_000, f'boot objects not frozen (freeze count {count})'; "
        "print('GC_BOOT_OK')"
    )
    result = subprocess.run(
        [sys.executable, str(manage_py), "shell", "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"manage.py shell failed:\n{result.stderr[-2000:]}"
    assert "GC_BOOT_OK" in result.stdout, result.stdout[-500:]
