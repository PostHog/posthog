import uuid
import asyncio

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
    update_tags,
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


@pytest.mark.asyncio
async def test_async_tasks_have_isolated_tags():
    reset_query_tags()

    # Use Events to guarantee interleaved execution
    task_a_set_tags = asyncio.Event()
    task_b_set_tags = asyncio.Event()

    results = {}

    async def task_a():
        # Task A sets its tags first
        tag_queries(team_id=100, user_id=1)
        task_a_set_tags.set()

        # Wait for Task B to set its tags
        await task_b_set_tags.wait()

        tags = get_query_tags()
        results["task_a"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    async def task_b():
        # Wait for Task A to set its tags first
        await task_a_set_tags.wait()

        # Task B sets its own tags (after Task A)
        tag_queries(team_id=200, user_id=2)
        task_b_set_tags.set()

        tags = get_query_tags()
        results["task_b"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    task_a_handle = asyncio.create_task(task_a())
    task_b_handle = asyncio.create_task(task_b())

    await task_a_handle
    await task_b_handle

    # Each task should see its own values, not contaminated by the other
    assert results["task_a"]["team_id"] == 100
    assert results["task_a"]["user_id"] == 1

    assert results["task_b"]["team_id"] == 200
    assert results["task_b"]["user_id"] == 2


@pytest.mark.asyncio
async def test_async_tasks_have_isolated_tags_with_update_tags():
    reset_query_tags()

    # Use Events to guarantee interleaved execution
    task_a_set_tags = asyncio.Event()
    task_b_set_tags = asyncio.Event()

    results = {}

    async def task_a():
        # Task A updates its tags first
        tags_to_update = QueryTags(team_id=100, user_id=1)
        update_tags(tags_to_update)
        task_a_set_tags.set()

        # Wait for Task B to update its tags
        await task_b_set_tags.wait()

        tags = get_query_tags()
        results["task_a"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    async def task_b():
        # Wait for Task A to update its tags first
        await task_a_set_tags.wait()

        # Task B updates its own tags (after Task A)
        tags_to_update = QueryTags(team_id=200, user_id=2)
        update_tags(tags_to_update)
        task_b_set_tags.set()

        tags = get_query_tags()
        results["task_b"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    task_a_handle = asyncio.create_task(task_a())
    task_b_handle = asyncio.create_task(task_b())

    await task_a_handle
    await task_b_handle

    # Each task should see its own values, not contaminated by the other
    assert results["task_a"]["team_id"] == 100
    assert results["task_a"]["user_id"] == 1

    assert results["task_b"]["team_id"] == 200
    assert results["task_b"]["user_id"] == 2


@pytest.mark.asyncio
async def test_async_tasks_have_isolated_tags_with_clear_tag():
    reset_query_tags()

    # Both tasks start with same initial tags
    tag_queries(team_id=100, user_id=50)

    # Use Events to guarantee interleaved execution
    task_a_cleared = asyncio.Event()
    task_b_cleared = asyncio.Event()

    results = {}

    async def task_a():
        # Task A clears user_id
        clear_tag("user_id")
        task_a_cleared.set()

        # Wait for Task B to clear team_id
        await task_b_cleared.wait()

        tags = get_query_tags()
        results["task_a"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    async def task_b():
        # Wait for Task A to clear user_id
        await task_a_cleared.wait()

        # Task B clears team_id (after Task A)
        clear_tag("team_id")
        task_b_cleared.set()

        tags = get_query_tags()
        results["task_b"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    task_a_handle = asyncio.create_task(task_a())
    task_b_handle = asyncio.create_task(task_b())

    await task_a_handle
    await task_b_handle

    # Task A cleared user_id, should still have team_id
    assert results["task_a"]["team_id"] == 100
    assert results["task_a"]["user_id"] is None

    # Task B cleared team_id, should still have user_id
    assert results["task_b"]["team_id"] is None
    assert results["task_b"]["user_id"] == 50
