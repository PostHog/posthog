from collections.abc import Iterator

import pytest

from posthog.temporal.tests.utils.logger import restored_structlog_config


@pytest.fixture(autouse=True)
def _restore_structlog_config() -> Iterator[None]:
    with restored_structlog_config():
        yield
