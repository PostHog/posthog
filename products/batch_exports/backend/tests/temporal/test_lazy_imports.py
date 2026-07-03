import sys
import types
import threading

import pytest

import products.batch_exports.backend.temporal as temporal_pkg

WORKFLOWS_MODULE = "products.batch_exports.backend.temporal.workflows"


def test_resolves_aggregator_names():
    assert isinstance(temporal_pkg.ACTIVITIES, list)
    assert isinstance(temporal_pkg.WORKFLOWS, list)
    assert temporal_pkg.ACTIVITIES
    assert temporal_pkg.WORKFLOWS


def test_non_aggregator_name_raises_attribute_error():
    # Falls through to a regular submodule import instead of eagerly loading the aggregator.
    with pytest.raises(AttributeError):
        temporal_pkg.__getattr__("definitely_not_an_attribute")


@pytest.fixture
def partial_workflows_module(monkeypatch):
    """Swap in a bare ``workflows`` module missing the aggregator names, mimicking the window
    where the real module is mid-initialization in sys.modules."""
    partial = types.ModuleType(WORKFLOWS_MODULE)
    monkeypatch.setitem(sys.modules, WORKFLOWS_MODULE, partial)
    monkeypatch.setattr(temporal_pkg, "_PARTIAL_MODULE_RETRY_SLEEP", 0.01)
    return partial


def test_waits_for_concurrent_import_to_finish(partial_workflows_module):
    # A concurrent context finishes binding the aggregator names shortly after we start resolving.
    def finish_import():
        partial_workflows_module.ACTIVITIES = ["activity"]

    timer = threading.Timer(0.05, finish_import)
    timer.start()
    try:
        assert temporal_pkg.__getattr__("ACTIVITIES") == ["activity"]
    finally:
        timer.cancel()


def test_raises_clear_error_when_names_never_bind(partial_workflows_module, monkeypatch):
    monkeypatch.setattr(temporal_pkg, "_PARTIAL_MODULE_RETRIES", 3)

    with pytest.raises(ImportError) as exc_info:
        temporal_pkg.__getattr__("ACTIVITIES")

    assert "still initializing" in str(exc_info.value)
    assert exc_info.value.name == "ACTIVITIES"
