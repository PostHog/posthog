from collections.abc import Callable

from django.db import transaction


def report_on_commit(callback: Callable[[], None]) -> None:
    def report() -> None:
        callback()

    transaction.on_commit(report, robust=True)
