from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def _temporal_loggers_at_info(caplog: pytest.LogCaptureFixture) -> None:
    """Run the Temporal loggers at INFO, as the production worker does.

    The Temporal loggers are stdlib `LoggerAdapter`s that reject structured
    keyword fields, and they only reach the rejecting call once the level lets
    the record through. At the default WARNING level an `info` call with a bad
    field is inert, so a crash that happens on every production tick passes here.
    """
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
