from datetime import UTC, datetime, timedelta

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
)

from django.test import override_settings

from parameterized import param, parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

OVERRIDES = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
NO_OVERRIDES = PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS

PUSHDOWN = "in(events.distinct_id, (SELECT"


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
class TestPersonIdFilterPrewhere(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        timestamp = datetime.now(UTC) - timedelta(days=1)
        self.person_ids: dict[str, str] = {}
        for distinct_id in ("kept", "merged", "other"):
            person = _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
            _create_event(event=distinct_id, distinct_id=distinct_id, team=self.team, timestamp=timestamp)
            self.person_ids[distinct_id] = str(person.uuid)
        flush_persons_and_events()
        create_person_id_override_by_distinct_id("merged", "kept", self.team.pk)

    @parameterized.expand(
        [
            param("equals", "person_id = '{kept}'", {"kept", "merged"}, pushdown=True),
            param("equals_absorbed_person", "person_id = '{merged}'", set(), pushdown=True),
            param("in", "person_id IN ('{kept}', '{other}')", {"kept", "merged", "other"}, pushdown=True),
            param("not_equals", "person_id != '{kept}'", {"other"}, pushdown=False),
            param("legacy_events_table", "person_id = '{kept}'", {"kept", "merged"}, pushdown=False, new_schema=False),
            param("no_overrides_mode", "person_id = '{merged}'", {"merged"}, pushdown=False, mode=NO_OVERRIDES),
            param(
                "explicit_prewhere",
                "person_id = '{kept}'",
                {"kept"},
                pushdown=False,
                prewhere="PREWHERE event = 'kept'",
            ),
        ]
    )
    def test_person_id_filter(
        self,
        _name: str,
        where: str,
        expected: set[str],
        *,
        pushdown: bool,
        new_schema: bool = True,
        mode: PersonsOnEventsMode = OVERRIDES,
        prewhere: str = "",
    ):
        response = execute_hogql_query(
            parse_select(f"SELECT event FROM events {prewhere} WHERE {where.format(**self.person_ids)}"),
            self.team,
            modifiers=HogQLQueryModifiers(personsOnEventsMode=mode, useNewEventsSchema=new_schema),
        )

        assert response.clickhouse is not None
        assert (PUSHDOWN in response.clickhouse) == pushdown
        assert {row[0] for row in response.results} == expected
