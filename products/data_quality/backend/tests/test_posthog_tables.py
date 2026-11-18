from uuid import uuid4

import pytest

from products.data_quality.backend.facade.enums import SubjectType
from products.data_quality.backend.logic.posthog_tables import TABLES, all_ids, by_id, by_name, names
from products.data_quality.backend.logic.subjects import resolve_subject


class TestPostHogTableRegistry:
    @pytest.mark.parametrize(
        ("name", "time_column"), [("events", "timestamp"), ("persons", "created_at"), ("groups", "created_at")]
    )
    def test_each_table_resolves_by_name_and_by_id(self, name: str, time_column: str) -> None:
        entry = by_name(name)

        assert entry is not None
        assert entry.time_column == time_column
        assert by_id(entry.id) is entry
        assert entry.id in all_ids()
        assert name in names()

    def test_an_id_that_is_no_table_resolves_to_nothing(self) -> None:
        assert by_id(uuid4()) is None
        assert by_id("not-a-uuid") is None
        assert by_name("orders") is None

    def test_columns_leave_out_the_joins_a_check_cannot_select(self) -> None:
        events = by_name("events")
        persons = by_name("persons")
        assert events is not None and persons is not None

        assert events.columns["timestamp"] == "datetime"
        assert persons.columns["properties"] == "json"
        for join in ("person", "pdi", "poe", "goe_0", "session"):
            assert join not in events.columns

    def test_an_id_the_registry_does_not_know_resolves_to_a_missing_subject(self) -> None:
        missing = resolve_subject(1, SubjectType.POSTHOG_TABLE, uuid4())

        assert not missing.exists
        assert missing.time_column is None

    def test_a_registered_table_resolves_without_touching_the_database(self) -> None:
        events = by_name("events")
        assert events is not None

        resolved = resolve_subject(1, SubjectType.POSTHOG_TABLE, events.id)

        assert resolved.exists
        assert resolved.queryable_name == "events"
        assert resolved.time_column == "timestamp"

    def test_every_table_has_a_distinct_stable_id(self) -> None:
        events = by_name("events")
        assert events is not None

        assert len(all_ids()) == len(TABLES)
        assert str(events.id) == "d4fb61da-50ae-59dc-a94f-f2036dfcfe49"
