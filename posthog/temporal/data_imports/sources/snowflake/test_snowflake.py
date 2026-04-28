import pytest

from posthog.temporal.data_imports.sources.snowflake.snowflake import _parse_clustering_key_leading_column


@pytest.mark.parametrize(
    "clustering_key,expected",
    [
        # Snowflake stores clustering keys wrapped in LINEAR(...). Unquoted
        # identifiers are uppercased to match the form Snowflake returns from
        # INFORMATION_SCHEMA.COLUMNS — otherwise the source-level membership
        # check `field_name in indexed_cols` misses on every clustering key
        # that was written in lowercase.
        ("LINEAR(created_at)", "CREATED_AT"),
        ("LINEAR(created_at, user_id)", "CREATED_AT"),
        ("LINEAR(CreatedAt)", "CREATEDAT"),
        # Quoted identifiers preserve case sensitivity in Snowflake — strip the
        # quotes and keep the case as-written.
        ('LINEAR("CreatedAt", user_id)', "CreatedAt"),
        ('LINEAR("created_at")', "created_at"),
        # Older / non-LINEAR forms appear unwrapped in INFORMATION_SCHEMA.
        ("created_at", "CREATED_AT"),
        ("  created_at  ", "CREATED_AT"),
        # Function expressions don't accelerate WHERE col >= … on the column
        # they wrap, so we conservatively report no leading column.
        ("LINEAR(DATE_TRUNC('day', created_at))", None),
        # Empty / malformed inputs.
        ("", None),
        (None, None),
        ("LINEAR(", None),
    ],
)
def test_parse_clustering_key_leading_column(clustering_key, expected):
    assert _parse_clustering_key_leading_column(clustering_key) == expected
