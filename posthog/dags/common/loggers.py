"""Dagster logger that routes op/asset logs through PostHog's structlog pipeline.

Dagster's default `colored_console_logger` writes plain colored text to the
process stdout. The PostHog Logs product is fed by the OTel collector scraping
each container's stdout and parsing structlog's JSON lines (see
`posthog/settings/logs.py`) — plain text isn't parseable, so Dagster job logs
never make it there as structured records the way Django app logs do.

This logger attaches no handler of its own: records propagate to the root
logger that `django.setup()` (run in `posthog/dags/__init__.py`) configured
with the structlog `ProcessorFormatter`. That gives Dagster's `context.log`
output the exact same JSON shape as Django logs — pretty console lines in dev,
single JSON lines in prod (controlled by `LOGGING_FORMATTER_NAME`).

It only replaces the *console* logger (`self._loggers` in Dagster's
`DagsterLogHandler`). The structured run-logs view in the Dagster UI is fed by
a separate built-in handler (`self._handlers`), so nothing is hidden from the
UI — only the raw stdout format changes.

Engine events (step/run lifecycle) are filtered out before they reach the root
formatter — they carry a non-serializable `DagsterEvent` the JSON renderer
can't encode, and they aren't useful in the Logs product anyway.
"""

import logging

import dagster


class _DropDagsterEngineEvents(logging.Filter):
    """Dagster routes both user `context.log` messages and engine events
    (STEP_START, RUN_SUCCESS, …) through the run loggers. Engine-event records
    carry a raw, non-JSON-serializable `DagsterEvent` in their `dagster_meta`,
    which the root structlog `JSONRenderer` (prod `LOGGING_FORMATTER_NAME=json`)
    can't encode — it would raise on every step/run event. We only want the
    user log messages in the Logs product, so drop the engine-event records.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        meta = getattr(record, "dagster_meta", None)
        return not (isinstance(meta, dict) and meta.get("dagster_event") is not None)


@dagster.logger(
    config_schema={
        "log_level": dagster.Field(str, is_required=False, default_value="INFO", description="The logger's threshold."),
        "name": dagster.Field(str, is_required=False, default_value="dagster", description="The name of the logger."),
    },
    description=(
        "Routes Dagster logs through PostHog's structlog pipeline (JSON to stdout, like Django) "
        "so the OTel collector ships them to the Logs product. Replaces colored_console_logger."
    ),
)
def structlog_console_logger(init_context: dagster.InitLoggerContext) -> logging.Logger:
    log = logging.getLogger(init_context.logger_config["name"])
    log.setLevel(init_context.logger_config["log_level"])
    # No handler: rely on propagation to the structlog-configured root logger.
    # `posthog/settings/logs.py` sets `disable_existing_loggers=True`, which can
    # disable a logger created before Django setup ran — re-enable defensively.
    log.disabled = False
    log.propagate = True
    # `getLogger` returns a process-wide singleton reused across runs, so guard
    # against stacking the filter on repeated logger instantiation.
    if not any(isinstance(f, _DropDagsterEngineEvents) for f in log.filters):
        log.addFilter(_DropDagsterEngineEvents())
    return log
