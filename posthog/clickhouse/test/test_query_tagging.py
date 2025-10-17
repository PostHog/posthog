import uuid

import pytest

from pydantic import ValidationError

from posthog.clickhouse.query_tagging import (
    Product,
    QueryTags,
    TemporalTags,
    clear_tag,
    create_base_tags,
    get_query_tag_value,
    get_query_tags,
    reset_query_tags,
    tag_queries,
    tags_context,
)


def test_create_base_tags():
    qt = create_base_tags(container_hostname="my-new-hostname")
    assert qt.container_hostname == "test"


def test_with_temporal():
    qt = create_base_tags()
    qt.with_temporal(TemporalTags(workflow_type="wt"))
    assert qt.model_dump(exclude_none=True) == {
        "container_hostname": "test",
        "git_commit": "test",
        "kind": "temporal",
        "service_name": "test",
        "temporal": {"workflow_type": "wt"},
    }


def test_simple_query_tags():
    uid = uuid.UUID("f3065cb7-10a5-4707-8910-a7c777896ac8")
    qt = QueryTags(
        team_id=1,
        name="my name",
        product=Product.API,
        http_request_id=uid,
        git_commit="",
        container_hostname="",
        service_name="",
    )
    assert qt.team_id == 1
    assert qt.user_id is None
    assert qt.org_id is None
    assert qt.name == "my name"
    assert qt.access_method is None
    assert qt.product == "api"
    assert qt.http_request_id == uid

    data = qt.to_json()
    assert (
        data
        == '{"team_id":1,"product":"api","name":"my name","http_request_id":"f3065cb7-10a5-4707-8910-a7c777896ac8","git_commit":"","container_hostname":"","service_name":""}'
    )


def test_constant_tags():
    want = QueryTags(git_commit="test", container_hostname="test", service_name="test")
    assert create_base_tags() == want
    reset_query_tags()
    assert get_query_tags() == want


def test_set_get():
    reset_query_tags()
    tag_queries(team_id=1, product=Product.API)

    assert get_query_tag_value("team_id") == 1
    assert get_query_tag_value("product") == "api"


def test_failure_on_incorrect_type():
    reset_query_tags()
    with pytest.raises(ValidationError):
        tag_queries(team_id="jeden")
    assert get_query_tags() == create_base_tags()


def test_clear_tag():
    reset_query_tags()
    clear_tag("team_id")
    assert get_query_tags() == create_base_tags()
    reset_query_tags()
    assert get_query_tags() == create_base_tags()
    tag_queries(team_id=123)
    assert get_query_tags() == create_base_tags(team_id=123)
    clear_tag("user_id")
    assert get_query_tags() == create_base_tags(team_id=123)
    clear_tag("team_id")
    assert get_query_tags() == create_base_tags()


def test_tags_context():
    reset_query_tags()
    # Set initial tags
    tag_queries(team_id=123)
    assert get_query_tags() == create_base_tags(team_id=123)

    # Modify tags within context
    with tags_context(user_id=312):
        tag_queries(cohort_id=777)
        assert get_query_tags() == create_base_tags(team_id=123, user_id=312, cohort_id=777)

        # Modify more
        tag_queries(name="another_value", team_id=1234)
        assert get_query_tags() == create_base_tags(team_id=1234, user_id=312, cohort_id=777, name="another_value")

    # Verify tags are restored
    assert get_query_tags() == create_base_tags(team_id=123)
