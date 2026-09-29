import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, patch_clickhouse_client_execute
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.printer import HogQLPrinter
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import get_query_tag_value
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PersonalAPIKey, PropertyDefinition, Team, User
from posthog.models.person.util import create_person_distinct_id
from posthog.models.person_group_membership.sql import SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.persons import add_distinct_id, create_person, delete_person

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.customer_analytics.backend.hogql_queries.account_persons import membership_source_query
from products.customer_analytics.backend.presentation.views.account_persons_serializers import (
    AccountPersonsQuerySerializer,
)
from products.customer_analytics.backend.test.factories import create_account


class TestAccountPersonsValidation(SimpleTestCase):
    def test_membership_table_is_only_namespaced(self) -> None:
        database = Database()
        assert database.get_table("posthog.person_group_membership").has_field("team_id")
        with self.assertRaises(QueryError):
            database.get_table("person_group_membership")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_membership_source_query(self) -> None:
        printer = HogQLPrinter(context=HogQLContext(team_id=1), pretty=True)
        assert printer.visit(membership_source_query(0, "acme")) == self.snapshot

    @parameterized.expand(
        [
            ({"limit": 0}, "limit"),
            ({"limit": 501}, "limit"),
            ({"offset": -1}, "offset"),
            ({"properties": "{}"}, "properties"),
            ({"properties": "not json"}, "properties"),
            ({"properties": '[{"key":"email","type":"event","operator":"exact","value":"a"}]'}, "properties"),
            ({"order_by": "email"}, "order_by"),
            ({"select": '["a"]', "order_by": "a DESC"}, "order_by"),
            ({"select": "not json"}, "select"),
            ({"select": "{}"}, "select"),
        ]
    )
    def test_invalid_parameters(self, data: dict, field: str) -> None:
        serializer = AccountPersonsQuerySerializer(data=data)
        assert not serializer.is_valid()
        assert field in serializer.errors


class TestAccountPersons(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.team.person_display_name_properties = ["name", "email"]
        self.team.save()
        config = self.team.customer_analytics_config
        config.account_group_type_index = 0
        config.save()
        self.account = create_account(team_id=self.team.id, external_id="acme")
        self.url = f"/api/projects/{self.team.id}/accounts/{self.account.id}/persons/"
        sync_execute(f"TRUNCATE TABLE {SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE}")
        self.addCleanup(sync_execute, f"TRUNCATE TABLE {SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE}")
        self.alice = create_person(
            team=self.team,
            distinct_ids=["alice", "alice-device"],
            properties={"name": "Alice", "email": "alice@example.com", "tier": "gold", "secret": "hidden"},
        )
        self.bob = create_person(
            team=self.team,
            distinct_ids=["bob"],
            properties={"name": "Bob", "email": "bob@example.com", "tier": "silver"},
        )
        self.seed("alice", 1, 3)
        self.seed("alice-device", 2, 5)
        self.seed("alice", 2, 4)
        self.seed("bob", 3, 4)
        self.seed("missing", 1, 9)
        outsider = create_person(
            team=self.team, distinct_ids=["outsider"], properties={"email": "outsider@example.com"}
        )
        self.seed("outsider", 1, 9, group_key="other-account")
        self.seed("outsider", 1, 9, index=1)
        other_team = Team.objects.create(organization=self.organization)
        self.seed("foreign-only", 1, 9, team_id=other_team.id)
        self.outsider = outsider

    def seed(
        self,
        distinct_id: str,
        first: int,
        last: int,
        *,
        group_key: str = "acme",
        index: int = 0,
        team_id: int | None = None,
    ) -> None:
        sync_execute(
            "INSERT INTO person_group_membership (team_id, group_type_index, group_key, distinct_id, first_seen, last_seen) VALUES",
            [
                (
                    team_id or self.team.id,
                    index,
                    group_key,
                    distinct_id,
                    datetime(2020, 1, first, tzinfo=UTC),
                    datetime(2020, 1, last, tzinfo=UTC),
                )
            ],
        )

    def get(self, **params: object) -> dict:
        if "select" in params:
            params["select"] = json.dumps(params["select"])
        response = self.client.get(self.url, data=params)
        assert response.status_code == 200, response.content
        return response.json()

    def test_page_aggregates_parts_and_current_distinct_ids(self) -> None:
        first = self.get(limit=1, select=["tier", "email"])
        assert first["has_more"]
        assert first["offset"] == 0
        alice = first["results"][0]
        assert alice["id"] == str(self.alice.uuid)
        assert alice["name"] == "Alice"
        assert alice["distinct_ids"] == ["alice", "alice-device"]
        assert alice["properties"] == {"tier": "gold", "email": "alice@example.com"}
        assert alice["account_first_seen"] == "2020-01-01T00:00:00Z"
        assert alice["account_last_seen"] == "2020-01-05T00:00:00Z"
        second = self.get(limit=1, offset=1)
        assert [row["id"] for row in second["results"]] == [str(self.bob.uuid)]
        assert not second["has_more"]

    @parameterized.expand(
        [
            ({"search": "alice@example.com"}, "alice"),
            ({"search": "alice-device"}, "alice"),
            ({"search": "Alice"}, "alice"),
            ({"search": "bob"}, "bob"),
            ({"properties": json.dumps([{"key": "tier", "operator": "exact", "value": "silver"}])}, "bob"),
            ({"select": ["tier"], "order_by": "-tier", "limit": 1}, "bob"),
            ({"order_by": "-account_first_seen", "limit": 1}, "bob"),
        ]
    )
    def test_search_filter_sort_after_membership(self, params: dict, expected: str) -> None:
        result = self.get(**params)
        assert [row["id"] for row in result["results"]] == [str(getattr(self, expected).uuid)]

    def test_property_keys_are_data_not_hogql(self) -> None:
        key = "custom, `column` ' OR true --"
        create_person(
            team=self.team, uuid=self.alice.uuid, distinct_ids=[], version=100, properties={key: {"nested": [1, True]}}
        )
        result = self.get(select=[key], order_by=key)
        alice = next(row for row in result["results"] if row["id"] == str(self.alice.uuid))
        assert alice["properties"] == {key: {"nested": [1, True]}}

    def test_current_properties(self) -> None:
        create_person(
            team=self.team,
            uuid=self.alice.uuid,
            distinct_ids=[],
            version=100,
            properties={"name": "New name", "tier": "platinum"},
        )
        result = self.get(select=["tier"], search="New name")
        assert result["results"][0]["properties"] == {"tier": "platinum"}
        assert result["results"][0]["name"] == "New name"

    def test_identity_merge_split_and_deleted_mapping(self) -> None:
        add_distinct_id(person=self.alice, distinct_id="bob", version=100)
        merged = self.get()
        assert len(merged["results"]) == 1
        assert merged["results"][0]["distinct_ids"] == ["alice", "alice-device", "bob"]
        split = create_person(team=self.team, distinct_ids=[], properties={"name": "Split"})
        add_distinct_id(person=split, distinct_id="alice-device", version=200)
        rows = {row["id"]: row for row in self.get()["results"]}
        assert set(rows) == {str(self.alice.uuid), str(split.uuid)}
        assert rows[str(self.alice.uuid)]["account_last_seen"] == "2020-01-04T00:00:00Z"
        assert rows[str(split.uuid)]["account_first_seen"] == "2020-01-02T00:00:00Z"
        create_person_distinct_id(self.team.id, "alice-device", str(split.uuid), version=300, is_deleted=True)
        assert [row["id"] for row in self.get()["results"]] == [str(self.alice.uuid)]

    def test_deleted_person_is_not_readable(self) -> None:
        delete_person(self.alice)
        assert [row["id"] for row in self.get()["results"]] == [str(self.bob.uuid)]

    def test_team_guard_and_injection_safe_key(self) -> None:
        result = execute_hogql_query("SELECT distinct_id FROM posthog.person_group_membership", team=self.team)
        assert {row[0] for row in result.results} == {"alice", "alice-device", "bob", "missing", "outsider"}
        result = execute_hogql_query(membership_source_query(0, "acme' OR 1=1 --"), team=self.team)
        assert result.results == []

    @parameterized.expand(
        [
            (["account:read"], 403),
            (["person:read"], 403),
            (["account:read", "person:read"], 200),
            (["account:write", "person:write"], 200),
        ]
    )
    def test_token_scopes(self, scopes: list[str], expected: int) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(user=self.user, label="test", secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()
        response = self.client.get(self.url, headers={"authorization": f"Bearer {token}"})
        assert response.status_code == expected, response.content

    def test_inaccessible_account_and_cross_project(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        viewer = User.objects.create_and_join(self.organization, "viewer@example.com", None)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=viewer, organization=self.organization),
        )
        self.client.force_login(viewer)
        assert self.client.get(self.url).status_code == 404
        other = Team.objects.create(organization=self.organization)
        assert (
            self.client.get(self.url.replace(f"/projects/{self.team.id}/", f"/projects/{other.id}/")).status_code == 404
        )

    def restrict(self, key: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name=key, type=PropertyDefinition.Type.PERSON, property_type="String"
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")

    def test_restricted_selection_name_search_and_filters(self) -> None:
        for key in ("secret", "name", "email"):
            self.restrict(key)
        rows = self.get(select=["tier", "secret", "email"])["results"]
        assert rows[0]["properties"] == {"tier": "gold"}
        assert rows[0]["name"] == str(self.alice.uuid)
        assert self.get(search="alice@example.com")["results"] == []
        filters = [{"key": "secret", "operator": "exact", "value": "hidden"}]
        assert self.client.get(self.url, data={"properties": json.dumps(filters)}).status_code == 400
        assert self.client.get(self.url, data={"select": '["secret"]', "order_by": "secret"}).status_code == 400

    def test_query_tags_and_slo_do_not_record_values(self) -> None:
        labels = {"has_filters": "true", "has_search": "true", "outcome": "success"}
        metric = "customer_analytics_account_persons_duration_seconds_count"
        duration_count = REGISTRY.get_sample_value(metric, labels) or 0
        result_sum = REGISTRY.get_sample_value("customer_analytics_account_persons_result_count_sum") or 0
        selected_sum = REGISTRY.get_sample_value("customer_analytics_account_persons_selected_property_count_sum") or 0
        tags = []

        def record_tags(execute: Callable[..., object], query: str, *args: object, **kwargs: object) -> object:
            tags.append(tuple(get_query_tag_value(key) for key in ("product", "feature", "name")))
            return execute(query, *args, **kwargs)

        with (
            patch("posthog.slo.events.posthoganalytics.capture") as capture,
            patch_clickhouse_client_execute(record_tags),
        ):
            result = self.get(
                select=["tier"],
                search="Alice",
                properties=json.dumps([{"key": "tier", "operator": "exact", "value": "gold"}]),
            )
        assert len(result["results"]) == 1
        events = [
            call.kwargs for call in capture.call_args_list if call.kwargs.get("event") == "slo_operation_completed"
        ]
        assert len(events) == 1
        props = events[0]["properties"]
        assert props["operation"] == "account_persons_list"
        assert props["target_ms"] == 500
        assert props["has_filters"] and props["has_search"]
        assert props["selected_property_count"] == 1 and props["result_count"] == 1
        assert "Alice" not in json.dumps(props) and "gold" not in json.dumps(props)
        assert ("customer_analytics", "query", "account-persons") in tags
        assert REGISTRY.get_sample_value(metric, labels) == duration_count + 1
        assert REGISTRY.get_sample_value("customer_analytics_account_persons_result_count_sum") == result_sum + 1
        assert (
            REGISTRY.get_sample_value("customer_analytics_account_persons_selected_property_count_sum")
            == selected_sum + 1
        )

    def test_flag_and_validation_gate(self) -> None:
        assert self.client.get(self.url, data={"limit": 0}).status_code == 400
        self.flag_mock.return_value = False
        assert self.client.get(self.url).status_code == 403
