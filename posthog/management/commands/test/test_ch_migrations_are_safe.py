import pytest

from posthog.management.commands.test_ch_migrations_are_safe import find_conflict_with_master

MASTER_MIGRATIONS = [("0001", "initial"), ("0393", "latest"), ("0029", "legacy")]


@pytest.mark.parametrize(
    "index, expected",
    [
        pytest.param("0394", None, id="after_the_last_one_on_master"),
        pytest.param("0393", "Migration 0393_new conflicts with master: 0393_latest", id="same_number"),
        pytest.param(
            "0123",
            "Migration 0123_new is numbered before 0393_latest, the last migration on master",
            id="free_number_before_the_last_one",
        ),
    ],
)
def test_find_conflict_with_master(index: str, expected: str | None) -> None:
    assert find_conflict_with_master(index, "new", MASTER_MIGRATIONS) == expected
