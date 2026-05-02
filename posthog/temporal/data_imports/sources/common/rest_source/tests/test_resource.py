from collections.abc import Iterator
from typing import Any

from posthog.temporal.data_imports.sources.common.rest_source.resource import Resource


def _simple_generator() -> Iterator[list[dict[str, Any]]]:
    yield [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
    yield [{"id": 3, "name": "charlie"}]


def _empty_generator() -> Iterator[list[dict[str, Any]]]:
    return
    yield  # unreachable, but makes this a generator


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
        hints = {"columns": {"name": {"data_type": "text"}}}
        resource = Resource(_simple_generator, name="users", hints=hints)
        assert resource._hints["columns"]["name"]["data_type"] == "text"
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

    def test_data_from_chains_parent_pages_into_child_items(self) -> None:
        """Dependent resources are driven by iterating the parent and passing
        each parent page to the child generator as the ``items`` kwarg."""
        parent = Resource(_simple_generator, name="parents", hints={})

        child_calls: list[list[dict[str, Any]]] = []

        def child_generator(items: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
            child_calls.append(items)
            for item in items:
                yield [{"parent_id": item["id"], "child_name": item["name"]}]

        child = Resource(
            child_generator,
            name="children",
            hints={},
            kwargs={},
            data_from=parent,
        )

        pages = list(child)

        # The child generator should be invoked once per parent page (2 pages),
        # and should see the parent items in each call.
        assert len(child_calls) == 2
        assert child_calls[0] == [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        assert child_calls[1] == [{"id": 3, "name": "charlie"}]

        # One child page per parent item (3 total), each a list of dicts.
        assert len(pages) == 3
        assert pages[0] == [{"parent_id": 1, "child_name": "alice"}]
        assert pages[1] == [{"parent_id": 2, "child_name": "bob"}]
        assert pages[2] == [{"parent_id": 3, "child_name": "charlie"}]

    def test_data_from_applies_parent_transforms_before_chaining(self) -> None:
        """Parent maps/filters run before the parent page reaches the child."""
        parent = Resource(_simple_generator, name="parents", hints={})
        parent.add_filter(lambda item: item["id"] != 2)
        parent.add_map(lambda item: {**item, "name": item["name"].upper()})

        seen_items: list[dict[str, Any]] = []

        def child_generator(items: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
            seen_items.extend(items)
            yield []

        child = Resource(
            child_generator,
            name="children",
            hints={},
            kwargs={},
            data_from=parent,
        )

        list(child)

        # id 2 filtered out; names upper-cased by the parent before chaining.
        assert seen_items == [
            {"id": 1, "name": "ALICE"},
            {"id": 3, "name": "CHARLIE"},
        ]
