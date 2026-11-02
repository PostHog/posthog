"""Lazy loads across peer rows that `FETCH_RAISE_ON_PEERS` blocked during the current test.

The fetch mode records each blocked load before it raises `FieldFetchBlocked`.
The root conftest fails the test when a record is left at the end of its call,
so a blocked load fails its test even when app code catches the exception.
"""

_blocked: list[str] = []


def record(message: str) -> None:
    _blocked.append(message)


def start_test() -> None:
    _blocked.clear()


def finish_test() -> list[str]:
    blocked = list(_blocked)
    _blocked.clear()
    return blocked
