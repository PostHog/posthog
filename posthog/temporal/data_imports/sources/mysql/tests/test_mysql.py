from posthog.temporal.data_imports.sources.mysql.mysql import _sanitize_identifier


def test_sanitize_identifier_with_digits():
    res = _sanitize_identifier("851")
    assert res == "`851`"
