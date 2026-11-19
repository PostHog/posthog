import sys
import json
import logging
from typing import Any

import pytest

import structlog

from posthog.settings.logs import LOGGING


class PaymentDeclined(Exception):
    pass


def _json_formatter() -> structlog.stdlib.ProcessorFormatter:
    config = {key: value for key, value in LOGGING["formatters"]["json"].items() if key != "()"}
    return structlog.stdlib.ProcessorFormatter(**config)


def _record(msg: Any, exc_info: Any) -> logging.LogRecord:
    return logging.LogRecord("test", logging.ERROR, __file__, 1, msg, None, exc_info)


def _raise_chained() -> None:
    try:
        raise KeyError("card")
    except KeyError as e:
        raise PaymentDeclined("card declined") from e


@pytest.mark.parametrize("from_structlog", [False, True])
def test_json_formatter_renders_otel_exception_attributes(from_structlog: bool) -> None:
    try:
        _raise_chained()
    except PaymentDeclined:
        exc_info = sys.exc_info()

    if from_structlog:
        record = _record({"event": "payment failed", "exc_info": exc_info}, None)
        record._logger = logging.getLogger("test")
        record._name = "error"
    else:
        record = _record("payment failed", exc_info)

    rendered = json.loads(_json_formatter().format(record))

    assert "exc_info" not in rendered
    assert "exception" not in rendered
    assert rendered["exception.type"] == "PaymentDeclined"
    assert rendered["exception.message"] == "card declined"
    stacktrace = rendered["exception.stacktrace"]
    assert "KeyError: 'card'" in stacktrace
    assert "The above exception was the direct cause of the following exception" in stacktrace
    assert stacktrace.endswith(f"{__name__}.PaymentDeclined: card declined\n")


class UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("no str")


def test_json_formatter_survives_exception_with_raising_str() -> None:
    try:
        raise UnprintableError()
    except UnprintableError:
        rendered = json.loads(_json_formatter().format(_record("payment failed", sys.exc_info())))

    assert rendered["exception.type"] == "UnprintableError"
    assert rendered["exception.message"] == "<exception str() failed>"
    assert "Traceback (most recent call last):" in rendered["exception.stacktrace"]
