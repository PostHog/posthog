import logging
import logging.config

from posthog.settings import logs


def _record(level: int) -> logging.LogRecord:
    return logging.LogRecord("test", level, __file__, 1, "message", args=(), exc_info=None)


def test_level_filters_split_info_from_warnings() -> None:
    max_info = logs.MaxLevelFilter(logging.INFO)

    assert max_info.filter(_record(logging.INFO))
    assert not max_info.filter(_record(logging.WARNING))


def test_logging_config_can_be_applied() -> None:
    logging.config.dictConfig({**logs.LOGGING, "disable_existing_loggers": False})


def test_default_console_logging_handler_keeps_default_stream() -> None:
    assert "stream" not in logs.LOGGING["handlers"]["console"]


def test_hypercache_info_logs_route_to_stdout_with_warnings_on_stderr() -> None:
    assert logs.LOGGING["handlers"]["console_stdout_info"]["stream"] == "ext://sys.stdout"
    assert "stream" not in logs.LOGGING["handlers"]["console_stderr_warning"]
    assert logs.LOGGING["loggers"]["posthog.storage.hypercache_verifier"]["handlers"] == [
        "console_stdout_info",
        "console_stderr_warning",
    ]
    assert logs.LOGGING["loggers"]["posthog.tasks.hypercache_verification"]["handlers"] == [
        "console_stdout_info",
        "console_stderr_warning",
    ]
