import sys
import subprocess

import pytest

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
# none. This is xfail on ``pr-60700-base`` because the lazy-router work regresses it; wire the offending
# receivers into ``AppConfig.ready()`` and remove this marker (``strict=True`` flips xpass to a failure
# once it's fixed, forcing the marker's removal).
_ROUTER_RECEIVER_DIFF = """
import os
import weakref

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django

django.setup()
from django.db.models import signals

_SIGNALS = ["pre_save", "post_save", "pre_delete", "post_delete", "m2m_changed", "pre_init", "post_init"]


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
    return out


before = _connected()
from posthog.api import rest_router  # noqa: F401 — building the aggregator imports ~200 viewsets
after = _connected()
print("\\n".join(sorted(after - before)))
"""


@pytest.mark.xfail(
    reason="lazy router defers signal-receiver connection off django.setup() — wire via AppConfig.ready()", strict=True
)
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
