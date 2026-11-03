from collections.abc import Iterator

import pytest

from posthog.temporal.tests.utils.asyncify import ConfigureExecutor, restored_asyncify_executor
from posthog.temporal.tests.utils.logger import restored_structlog_config


@pytest.fixture(autouse=True)
def _restore_structlog_config() -> Iterator[None]:
    with restored_structlog_config():
        yield


@pytest.fixture
def asyncify_executor() -> Iterator[ConfigureExecutor]:
    with restored_asyncify_executor() as configure:
        yield configure
