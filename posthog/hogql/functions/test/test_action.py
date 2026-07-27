from typing import Any

import pytest
from posthog.test.base import (
    BaseTest,
    QueryMatchingTest,
    _create_action,
    _create_event,
    _create_person,
    flush_persons_and_events,
)

from django.conf import settings

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_response_in_tests

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.uuidt import UUIDT

from products.actions.backend.models.action import Action


def _create_action_with_property(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(
        team=team,
        name=name,
        steps_json=[
            {
                "event": name,
                "url": "https://posthog.com/feedback/123?vip=1",
                "url_matching": "exact",
            }
        ],
    )
    return action


class TestAction(BaseTest, QueryMatchingTest):
    snapshot: Any
    allow_dual_schema_snapshots = True
    maxDiff = None

    def _create_random_events(self) -> str:
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        _create_person(
            properties={"$os": "Chrome", "random_uuid": random_uuid},
            team=self.team,
            distinct_ids=["bla"],
            is_identified=True,
        )
        _create_event(
            distinct_id="bla",
            event=random_uuid,
            team=self.team,
            properties={"$current_url": "https://posthog.com/feedback/123?vip=1"},
        )
        _create_event(distinct_id="bla", event=random_uuid + "::extra", team=self.team)
        flush_persons_and_events()
        return random_uuid

    def test_matches_action_name(self):
        random_uuid = self._create_random_events()
        _create_action(team=self.team, name=random_uuid)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE matchesAction('{random_uuid}')",
            self.team,
        )

        assert response.results is not None
        assert len(response.results) == 1
        assert response.results[0][0] == random_uuid

    def test_matches_action_id(self):
        random_uuid = self._create_random_events()
        action = _create_action(team=self.team, name=random_uuid)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE matchesAction({action.pk})",
            self.team,
        )
        assert response.results is not None
        assert len(response.results) == 1
        assert response.results[0][0] == random_uuid

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_matches_action_with_alias(self):
        random_uuid = self._create_random_events()
        _create_action_with_property(team=self.team, name=random_uuid)
        response = execute_hogql_query(
            f"SELECT event FROM events AS e WHERE matchesAction('{random_uuid}')",
            self.team,
        )

        formatted_response = pretty_print_response_in_tests(response, self.team.pk)
        use_new_events_schema_snapshot = (
            settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA and "events_json" in formatted_response.lower()
        )
        assert formatted_response == self._schema_snapshot(use_new_events_schema_snapshot)
        assert response.results is not None
        assert len(response.results) == 1
        assert response.results[0][0] == random_uuid


class TestMatchesActionAccessControl(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.membership.level = OrganizationMembership.Level.MEMBER
        self.membership.save()
        self.action = Action.objects.create(
            team=self.team, name="restricted action", steps_json=[{"event": "$pageview"}]
        )

    def _set_access_level(self, access_level: str) -> None:
        from ee.models.rbac.access_control import AccessControl

        AccessControl.objects.create(
            team=self.team,
            resource="action",
            resource_id=str(self.action.pk),
            access_level=access_level,
            organization_member=self.membership,
        )

    def _resolve(self, reference: str) -> None:
        context = HogQLContext(team=self.team, team_id=self.team.pk, user=self.user, enable_select_queries=True)
        prepare_ast_for_printing(
            parse_select(f"SELECT count() FROM events WHERE matchesAction({reference})"),
            context,
            dialect="clickhouse",
        )

    @parameterized.expand([("by id",), ("by name",)])
    def test_action_the_user_cannot_read_is_not_resolved(self, reference_kind: str):
        self._set_access_level("none")
        reference = str(self.action.pk) if reference_kind == "by id" else f"'{self.action.name}'"

        with self.assertRaisesMessage(QueryError, f"You don't have access to action #{self.action.pk}"):
            self._resolve(reference)

    def test_readable_action_is_still_resolved(self):
        self._set_access_level("viewer")

        self._resolve(str(self.action.pk))
