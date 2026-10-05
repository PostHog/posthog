from collections.abc import Iterator

import pytest

import structlog


@pytest.fixture(autouse=True)
def _restore_structlog_config() -> Iterator[None]:
    # configure_logger replaces the process-wide structlog config. Without this restore, a test that
    # binds the logger to its own event loop leaves that binding to every later test on the worker,
    # which then produces log lines to a closed loop.
    previous_config = structlog.get_config()
    previously_configured = structlog.is_configured()
    yield
    if previously_configured:
        structlog.configure(**previous_config)
    else:
        structlog.reset_defaults()
