from posthog.clickhouse.query_tagging import tag_queries, get_query_tags, tags_context, clear_tag, reset_query_tags


def test_clear_tag():
    clear_tag("some")
    reset_query_tags()
    assert get_query_tags() == {}
    tag_queries(another=True)
    assert get_query_tags() == {"another": True}
    clear_tag("some")
    assert get_query_tags() == {"another": True}
    clear_tag("another")
    assert get_query_tags() == {}


def test_tags_context():
    reset_query_tags()
    # Set initial tags
    tag_queries(initial="value")
    assert get_query_tags() == {"initial": "value"}

    # Modify tags within context
    with tags_context(in_context="true"):
        tag_queries(test="test_value")
        assert get_query_tags() == {"initial": "value", "test": "test_value", "in_context": "true"}

        # Modify more
        tag_queries(another="another_value", initial="not a value")
        assert get_query_tags() == {
            "initial": "not a value",
            "test": "test_value",
            "another": "another_value",
            "in_context": "true",
        }

    # Verify tags are restored
    assert get_query_tags() == {"initial": "value"}
