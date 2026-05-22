import pytest

from posthog.settings.utils import POSTGRES_IDENTIFIER_MAX_LENGTH, build_postgres_test_db_name


def test_build_postgres_test_db_name_truncates_long_base_with_long_suffix() -> None:
    suffix = "_" + ("s" * 39)

    database_name = build_postgres_test_db_name("posthog_" + ("x" * 200), suffix=suffix)

    assert len(database_name) <= POSTGRES_IDENTIFIER_MAX_LENGTH
    assert database_name.endswith(suffix)


def test_build_postgres_test_db_name_rejects_suffix_that_leaves_no_base_space() -> None:
    suffix = "_" + ("s" * 49)

    with pytest.raises(ValueError, match="Suffix .* is too long for database name generation"):
        build_postgres_test_db_name("posthog_" + ("x" * 200), suffix=suffix)
