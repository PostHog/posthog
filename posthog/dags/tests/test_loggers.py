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
    "error_tracking",
    "growth",
    "ingestion",
    "llm_analytics",
    "logs",
    "posthog_ai",
    "revenue_analytics",
    "shared",
    "web_analytics",
]


def _build(config: dict | None = None) -> logging.Logger:
    return structlog_console_logger(dagster.build_init_logger_context(logger_config=config or {}))


def test_logger_has_no_handler_and_propagates_to_root():
    # The whole point: no handler of its own, so records propagate to the
    # structlog-configured root logger and come out as JSON like Django.
    log = _build()
    assert log.handlers == []
    assert log.propagate is True
    assert log.disabled is False


def test_logger_defaults_match_django_level_and_name():
    log = _build()
    assert log.name == "dagster"
    assert log.level == logging.INFO


def test_logger_respects_configured_level():
    log = _build({"log_level": "DEBUG", "name": "dagster"})
    assert log.level == logging.DEBUG


def test_locations_export_single_shared_logger_instance():
    assert loggers == {"console": structlog_console_logger}


@pytest.mark.parametrize("module_name", LOCATION_MODULES)
def test_every_location_wires_the_shared_console_logger(module_name):
    module = importlib.import_module(f"posthog.dags.locations.{module_name}")
    assert module.defs.loggers.get("console") is structlog_console_logger
