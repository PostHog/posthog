from collections.abc import Callable
from typing import Any

ParserExceptionReporter = Callable[[Exception, dict[str, Any] | None], None]

_parser_exception_reporter: ParserExceptionReporter | None = None


def set_parser_exception_reporter(reporter: ParserExceptionReporter | None) -> None:
    global _parser_exception_reporter

    _parser_exception_reporter = reporter


def report_parser_exception(exception: Exception, additional_properties: dict[str, Any] | None = None) -> None:
    if _parser_exception_reporter is not None:
        _parser_exception_reporter(exception, additional_properties)
