from collections.abc import Callable
from contextlib import ExitStack
from typing import NoReturn

from django.test import SimpleTestCase

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import get_client_from_pool


def _forbid_clickhouse(_original: Callable[..., object], *_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("ClickHouse access is not allowed in ClickhouseFreeSimpleTestCase")


class ClickhouseFreeSimpleTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        stack.enter_context(sync_execute._temp_patch(_forbid_clickhouse))
        stack.enter_context(get_client_from_pool._temp_patch(_forbid_clickhouse))
        super().setUpClass()
