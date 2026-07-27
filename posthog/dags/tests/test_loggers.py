import logging
import importlib

import pytest

import dagster

from posthog.dags.common.loggers import structlog_console_logger
from posthog.dags.locations import loggers

# Every code location module under `posthog/dags/locations/`. The sweep below
# guards against a new location forgetting to wire `loggers=loggers`.
LOCATION_MODULES = [
    "analytics_platform",
    "billing",
    "clickhouse",
    "data_stack",
    "growth",
    "ingestion",
    "logs",
    "posthog_ai",
    "revenue_analytics",
    "shared",
    "web_analytics",
]


# `getLogger` returns a process-wide singleton, so tests that mutate the logger
# (level, filters) use distinct names to avoid leaking state across tests under
# random ordering.
def _build(config: dict | None = None, *, name: str = "dagster") -> logging.Logger:
    merged = {"name": name, **(config or {})}
    return structlog_console_logger(dagster.build_init_logger_context(logger_config=merged))


def _record(*, dagster_event) -> logging.LogRecord:
    rec = logging.LogRecord("dagster", logging.INFO, __file__, 1, "msg", None, None)
    rec.dagster_meta = {"dagster_event": dagster_event}
    return rec


def test_logger_has_no_handler_and_propagates_to_root():
    # The whole point: no handler of its own, so records propagate to the
    # structlog-configured root logger and come out as JSON like Django.
    log = _build(name="dagster-test-propagate")
    assert log.handlers == []
    assert log.propagate is True
    assert log.disabled is False


def test_logger_defaults_match_django_level_and_name():
    log = _build()
    assert log.name == "dagster"
    assert log.level == logging.INFO


def test_logger_respects_configured_level():
    log = _build({"log_level": "DEBUG"}, name="dagster-test-level")
    assert log.level == logging.DEBUG


def test_engine_event_records_are_dropped_but_messages_pass():
    # Engine events carry a non-serializable DagsterEvent the root JSONRenderer
    # can't encode; only plain user log messages should propagate.
    log = _build(name="dagster-test-filter")
    assert not log.filter(_record(dagster_event=object()))
    assert log.filter(_record(dagster_event=None))


def test_locations_export_single_shared_logger_instance():
    assert loggers == {"console": structlog_console_logger}


@pytest.mark.parametrize("module_name", LOCATION_MODULES)
def test_every_location_wires_the_shared_console_logger(module_name):
    module = importlib.import_module(f"posthog.dags.locations.{module_name}")
    assert module.defs.loggers.get("console") is structlog_console_logger
