from collections.abc import AsyncGenerator
from typing import Any

from posthog.temporal.data_imports.sources.common.rest_source.resource import Resource


async def _simple_generator() -> AsyncGenerator[Any, Any]:
    yield [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
    yield [{"id": 3, "name": "charlie"}]


async def _empty_generator() -> AsyncGenerator[Any, Any]:
    return
    yield  # make it an async generator


class TestResource:
    def test_iteration_yields_pages(self) -> None:
        resource = Resource(_simple_generator, name="test", hints={})
        pages = list(resource)
        assert len(pages) == 2
        assert pages[0] == [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        assert pages[1] == [{"id": 3, "name": "charlie"}]

    def test_add_map_transforms_items(self) -> None:
        resource = Resource(_simple_generator, name="test", hints={})
        resource.add_map(lambda item: {**item, "name": item["name"].upper()})
        pages = list(resource)
        assert pages[0][0]["name"] == "ALICE"
        assert pages[0][1]["name"] == "BOB"

    def test_add_filter_removes_items(self) -> None:
        resource = Resource(_simple_generator, name="test", hints={})
        resource.add_filter(lambda item: item["id"] > 1)
        pages = list(resource)
        all_items = [item for page in pages for item in page]
        assert len(all_items) == 2
        assert all(item["id"] > 1 for item in all_items)

    def test_add_map_chains(self) -> None:
        resource = Resource(_simple_generator, name="test", hints={})
        result = resource.add_map(lambda x: x)
        assert result is resource

    def test_add_filter_chains(self) -> None:
        resource = Resource(_simple_generator, name="test", hints={})
        result = resource.add_filter(lambda x: True)
        assert result is resource

    def test_hints_accessible(self) -> None:
        hints = {"primary_key": "id", "columns": {"name": {"data_type": "text"}}}
        resource = Resource(_simple_generator, name="users", hints=hints)
        assert resource._hints["primary_key"] == "id"
        assert resource.name == "users"

    def test_empty_generator(self) -> None:
        resource = Resource(_empty_generator, name="empty", hints={})
        pages = list(resource)
        assert pages == []

    def test_filter_and_map_combined(self) -> None:
        resource = Resource(_simple_generator, name="test", hints={})
        resource.add_filter(lambda item: item["id"] <= 2)
        resource.add_map(lambda item: {**item, "processed": True})
        pages = list(resource)
        all_items = [item for page in pages for item in page]
        assert len(all_items) == 2
        assert all(item.get("processed") is True for item in all_items)
