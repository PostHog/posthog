import pytest

from posthog.temporal.data_imports.sources.snowflake.snowflake import _parse_clustering_key_leading_column


@pytest.mark.parametrize(
    "clustering_key,expected",
    [
        # Snowflake stores clustering keys wrapped in LINEAR(...).
        ("LINEAR(created_at)", "created_at"),
        ("LINEAR(created_at, user_id)", "created_at"),
        # Quoted identifiers preserve case sensitivity in Snowflake — strip the
        # quotes for comparison against the column-name strings we receive
        # elsewhere in schema discovery.
        ('LINEAR("CreatedAt", user_id)', "CreatedAt"),
        # Older / non-LINEAR forms appear unwrapped in INFORMATION_SCHEMA.
        ("created_at", "created_at"),
        ("  created_at  ", "created_at"),
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
