import os
import re
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
    "temporalio",  # Temporal SDK — only workers and call-time service paths need it (gated on sys.modules)
    "modal",  # Modal SDK — only the tasks/notebooks sandbox runtime needs it
    "aiohttp",  # async HTTP — pulled by slack async client / temporal clickhouse, both deferred
    "s3fs",  # S3 filesystem — only warehouse delete/import paths need it
    "pandas",  # only query/export paths need it — reached via clickhouse_connect's import-time probe
    "pyarrow",  # arrow tables — reached via pandas.compat and batch-export internals, both deferred
    "numpy",  # alert detectors / weighted sampling / warehouse coercion — all call-time now
    "posthog.schema",  # the generated pydantic data model (~2s) — enums live in posthog.schema_enums
    "posthog.hogql.query",  # query execution entrypoint — drags the layers below in
    "posthog.hogql_queries",  # the query-runner layer (every insight runner)
    "posthog.api.services.query",  # API query service — viewset-request-time only
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


# ``django.setup()`` above does NOT load the URLconf, so the bare-setup guard is blind to imports
# that only ride in via URL resolution (which every web worker and ``manage.py check`` pays). The
# canonical culprit is the Gemini SDK (``google.genai``): ``types.py`` triggers slow pydantic schema
# generation, and it was dragged onto the boot path because ``session_recording_api`` (reachable from
# URL loading) imports the session-summary Temporal workflow at module scope, whose package
# ``__init__`` eagerly pulls every video activity — several of which imported ``google.genai`` at
# module level. This reproduces that exact import (the one at ``session_recording_api.py`` line 115)
# and asserts it no longer drags in the SDK: the Gemini imports must be deferred into the activities
# that run them. Guarding the specific chain rather than the whole URLconf keeps this from flapping on
# unrelated Gemini callers that only load lazily via the API router.
_WORKFLOW_IMPORT_GENAI = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
import sys
import importlib
importlib.import_module("posthog.temporal.session_replay.session_summary.workflow")
print("\\n".join(sorted(m for m in sys.modules if m == "google.genai" or m.startswith("google.genai."))))
"""


def test_session_summary_workflow_import_does_not_pull_gemini_sdk() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _WORKFLOW_IMPORT_GENAI],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"django.setup() or the workflow import failed:\n{result.stderr[-2000:]}"
    loaded = [m for m in result.stdout.splitlines() if m]
    assert not loaded, (
        f"Importing the session-summary workflow dragged the Gemini SDK onto the import path: {loaded}. "
        "session_recording_api imports this workflow at module scope, so a module-level "
        "'from google.genai import ...' (or an import of posthoganalytics.ai.gemini, which pulls it) in "
        "any of its activities makes every web worker and `manage.py check` pay the SDK's slow pydantic "
        "schema generation at boot. Defer the import into the activity/function that uses it with a "
        "`# noqa: PLC0415`."
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
# The full URLconf, not just rest_router: it builds the router AND imports the product url
# modules urls.py pulls directly — the path where latent import cycles have twice detonated.
import importlib
importlib.import_module("posthog.urls")
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
    assert result.returncode == 0, (
        "django.setup() or the cold URLconf import failed — if the traceback shows a partially "
        f"initialized module, an import cycle only ever resolved by import-order luck:\n{result.stderr[-2000:]}"
    )
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
from django.contrib.auth import signals as auth_signals
from django.db.models import signals
from posthog.models.signals import model_activity_signal

_SIGNALS = ["pre_save", "post_save", "pre_delete", "post_delete", "m2m_changed", "pre_init", "post_init"]
# model_activity_signal is PostHog's custom audit-log signal, not a django.db.models one. Its
# `handle_*_change` receivers live in viewset modules, so they are exactly the kind that the eager
# router used to wire as a side effect — include it or this whole class of regression is invisible.
# Auth signals are included for parity with the setup-receivers baseline: an auth receiver wired
# only via a viewset import would otherwise slip past both guards.
_CUSTOM_SIGNALS = {
    "model_activity": model_activity_signal,
    "user_logged_in": auth_signals.user_logged_in,
    "user_logged_out": auth_signals.user_logged_out,
    "user_login_failed": auth_signals.user_login_failed,
}


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
# The full URLconf, not just rest_router — see the model-diff capture above.
import importlib
importlib.import_module("posthog.urls")
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
# This pins the COMPLETE set of first-party receivers connected at setup against a committed baseline —
# a hand-curated "one representative per relocation" list proved both fiddly and incomplete (several
# ready()-wired receivers were never pinned). A receiver missing from the live set is silent audit/cache
# loss; an unexpected one is a new wiring to record deliberately. Regenerate the file with:
#   UPDATE_SETUP_RECEIVERS_BASELINE=1 pytest posthog/test/test_startup_import_budget.py -k receivers_match
# Known granularity limit: receivers created in a loop share one qualname (e.g. the org-cache
# _connect_invalidation closures), so the set can't see one of their senders being dropped —
# Django stores sender identity as id(), which is not stable enough to snapshot.
_RECEIVERS_BASELINE = Path(__file__).parent / "setup_receivers_baseline.txt"

_SETUP_RECEIVERS_CAPTURE = """
import os
import weakref

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django

django.setup()
from django.contrib.auth import signals as auth_signals
from django.db.models import signals as model_signals
from posthog.models.signals import model_activity_signal

_FIRST_PARTY = ("posthog.", "products.", "ee.", "common.")
_SIGNALS = {
    name: getattr(model_signals, name)
    for name in ("pre_save", "post_save", "pre_delete", "post_delete", "m2m_changed", "pre_init", "post_init")
}
_SIGNALS |= {name: getattr(auth_signals, name) for name in ("user_logged_in", "user_logged_out", "user_login_failed")}
_SIGNALS["model_activity"] = model_activity_signal

out = set()
for signal_name, signal in _SIGNALS.items():
    for entry in signal.receivers:
        ref = entry[1]
        fn = ref() if isinstance(ref, weakref.ReferenceType) else ref
        if fn is None:
            continue
        module = getattr(fn, "__module__", "")
        qualname = getattr(fn, "__qualname__", "")
        if not module or not qualname:
            continue  # partials/lambdas have no stable name; their repr would embed addresses
        path = f"{module}.{qualname}"
        if path.startswith(_FIRST_PARTY):
            out.add(f"{signal_name}:{path}")
print("\\n".join(sorted(out)))
"""


def test_setup_receivers_match_baseline() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _SETUP_RECEIVERS_CAPTURE],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"receiver snapshot failed:\n{result.stderr[-2000:]}"
    connected = {line for line in result.stdout.splitlines() if ":" in line}
    assert len(connected) > 20, f"implausibly few receivers captured ({len(connected)}) — capture broken?"

    if os.environ.get("UPDATE_SETUP_RECEIVERS_BASELINE"):
        header = (
            "# First-party signal receivers connected after a bare django.setup(), as signal:module.qualname.\n"
            "# Maintained by test_setup_receivers_match_baseline — regenerate with:\n"
            "#   UPDATE_SETUP_RECEIVERS_BASELINE=1 pytest posthog/test/test_startup_import_budget.py -k receivers_match\n"
            "# A receiver disappearing from this set means it connects in NO process (silent audit/cache loss):\n"
            "# restore its AppConfig.ready() wiring instead of deleting the line.\n"
        )
        _RECEIVERS_BASELINE.write_text(header + "\n".join(sorted(connected)) + "\n")
        return

    baseline = {line for line in _RECEIVERS_BASELINE.read_text().splitlines() if line and not line.startswith("#")}
    missing = sorted(baseline - connected)
    unexpected = sorted(connected - baseline)
    assert not missing, (
        f"These receivers are in setup_receivers_baseline.txt but NOT connected at django.setup(): {missing}. "
        "Their wiring was likely dropped (e.g. a 'remove unused import' cleanup deleted a # noqa: F401 "
        "side-effect import from an AppConfig.ready()), so they connect in no process and their audit/cache "
        "writes silently stop. Restore the ready() wiring in the owning app; only remove a baseline line when "
        "the receiver itself was deliberately deleted."
    )
    assert not unexpected, (
        f"These receivers connect at django.setup() but are not in setup_receivers_baseline.txt: {unexpected}. "
        "If the new wiring is deliberate (receiver in an import-light module, imported from the owning "
        "AppConfig.ready() — see docs/internal/django-startup-time.md), record it: "
        "UPDATE_SETUP_RECEIVERS_BASELINE=1 pytest posthog/test/test_startup_import_budget.py -k receivers_match"
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


# Forward-looking counterpart to FORBIDDEN_AT_SETUP: that list catches *known* evicted modules
# returning; this catches a *new* heavy import nobody has named yet. There are deliberately no
# per-entry time budgets — absolute timings flake in CI — time is only the materiality gate
# for packages absent from the baseline. Captured with GC disabled, because a migrating gen2
# pause (~100ms) otherwise gets booked as self-time of whatever innocent module was executing.
_NEW_IMPORT_THRESHOLD_MS = 100
_FIRST_PARTY_ROOTS = ("posthog", "products", "ee", "common")
_IMPORT_BASELINE = Path(__file__).parent / "setup_import_baseline.txt"

_IMPORTTIME_CAPTURE = """
import gc
import os
gc.disable()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
"""


def _capture_setup_import_costs() -> dict[str, int]:
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", _IMPORTTIME_CAPTURE],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"django.setup() failed:\n{result.stderr[-2000:]}"

    costs: dict[str, int] = {}
    for line in result.stderr.splitlines():
        match = re.match(r"import time:\s+(\d+) \|\s+\d+ \| +(\S+)$", line)
        if not match:
            continue
        self_us, module = int(match.group(1)), match.group(2)
        root = module.split(".")[0]
        if root in _FIRST_PARTY_ROOTS:
            # judged per module: aggregating posthog.* would be one permanent offender
            costs[module] = self_us
        else:
            costs[root] = costs.get(root, 0) + self_us
    return costs


def test_no_new_heavy_imports_at_setup() -> None:
    baseline = {
        line.split("#")[0].strip() for line in _IMPORT_BASELINE.read_text().splitlines() if line.split("#")[0].strip()
    }
    contradictions = baseline & set(FORBIDDEN_AT_SETUP)
    assert not contradictions, (
        f"These names are in BOTH setup_import_baseline.txt and FORBIDDEN_AT_SETUP: {sorted(contradictions)}. "
        "The baseline permits what the forbidden list bans — someone likely baselined a module to dodge the "
        "new-import check while it remains deliberately evicted. Remove it from the baseline and defer the "
        "import that pulled it back in."
    )
    # Two captures, per-name minimum: the first boot on a cold machine pays page-cache misses
    # that can double a package's apparent cost (django measured 116ms cold vs ~67ms warm);
    # the minimum converges on the stable warm number, so the threshold compares like with like.
    first, second = _capture_setup_import_costs(), _capture_setup_import_costs()
    costs = {name: min(us, second.get(name, us)) for name, us in first.items()}

    threshold_us = _NEW_IMPORT_THRESHOLD_MS * 1000
    offenders = {name: us for name, us in costs.items() if us >= threshold_us and name not in baseline}
    assert not offenders, (
        f"New heavy import(s) appeared on the django.setup() path: "
        f"{ {name: f'{us / 1000:.0f}ms' for name, us in sorted(offenders.items(), key=lambda kv: -kv[1])} }. "
        "Every process (web, celery, temporal, migrate, shell, every CI job) now pays this on every boot. "
        "DO NOT add the package to setup_import_baseline.txt to make this pass — defer the import instead: "
        "function-local with `# noqa: PLC0415`, TYPE_CHECKING for type-only uses, a PEP 562 lazy facade for "
        "package aggregators, or a light activity_logging/visibility module for AppConfig.ready() wiring. "
        "Read docs/internal/django-startup-time.md for the patterns and the traps. To find the door, run: "
        "python -X importtime -c 'import gc; gc.disable(); import django; django.setup()' and trace the first "
        "importer of the offending package. Only if the package is genuinely required by every process during "
        "django.setup() may it be baselined, with a comment justifying why."
    )


# Counterpart to the lazy-router guard for WEB specifically: the router must NOT build at a
# bare django.setup() (every process pays), but it MUST build at web-entrypoint import —
# pre-fork, so workers share it copy-on-write. Without this, each worker builds the router
# on its first live request (k8s probes short-circuit in middleware and never warm it),
# which measured at multiple seconds per worker after every deploy.
def test_web_entrypoint_prebuilds_the_router() -> None:
    probe = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import posthog.wsgi  # noqa: F401 — the real web entry; builds the app and resolves the URLconf
import sys
assert "posthog.api.rest_router" in sys.modules, "wsgi import did not build the API router"
from django.urls import get_resolver
assert get_resolver()._populated or get_resolver().url_patterns, "URLconf not resolved"
print("WSGI_PREBUILD_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"posthog.wsgi import failed:\n{result.stderr[-2000:]}"
    assert "WSGI_PREBUILD_OK" in result.stdout, result.stdout[-500:]
