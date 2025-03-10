from posthog.clickhouse.query_tagging import tag_queries, get_query_tags, tags_context


def test_tags_context():
    # Set initial tags
    tag_queries(initial="value")
    assert get_query_tags() == {"initial": "value"}

    # Modify tags within context
    with tags_context(in_context="true"):
        tag_queries(test="test_value")
        assert get_query_tags() == {"initial": "value", "test": "test_value"}

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
