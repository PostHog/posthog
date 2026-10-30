import json
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import CacheMissResponse, QueryStatus

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.models import OrganizationMembership, PropertyDefinition, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.persons import create_person

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.customer_analytics.backend.logic.account_persons import AccountPersonsReader
from products.customer_analytics.backend.models import TeamCustomerAnalyticsConfig
from products.customer_analytics.backend.test.factories import create_account

FLAG_CHECK = "products.customer_analytics.backend.logic.account_persons.posthog_feature_flag_enabled"


class TestMembershipSchema(QueryMatchingTest, SimpleTestCase):
    def test_source_resolves_current_mappings_and_binds_account_key(self) -> None:
        team = Team(id=123, project_id=123)
        group_key = "workspace' OR 1 = 1 --"
        reader = AccountPersonsReader(team=team, user=User(), group_type_index=0, group_key=group_key)
        context = HogQLContext(
            team_id=team.pk,
            team=team,
            database=Database(),
            enable_select_queries=True,
            restricted_properties=set(),
            use_new_events_schema=False,
        )
        sql, _ = prepare_and_print_ast(reader.get_source_query(), context=context, dialect="clickhouse")
        self.assertQueryMatchesSnapshot(sql)
        assert group_key not in sql
        assert group_key in context.values.values()


@override_settings(HOGQL_MATERIALIZED_CTE_SUPPORTED=True)
class TestAccountUsersQuery(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch(FLAG_CHECK, return_value=True))
        TeamCustomerAnalyticsConfig.objects.update_or_create(team=self.team, defaults={"account_group_type_index": 0})
        self.account = create_account(team_id=self.team.pk, external_id="workspace-demo")
        self.endpoint = f"/api/projects/{self.team.pk}/query/"
        self.first = create_person(
            team=self.team,
            distinct_ids=["member-one", "member-one-alias"],
            properties={"email": "first@example.com", "name": "First member", "plan": "paid", "private_note": "hidden"},
        )
        self.second = create_person(
            team=self.team, distinct_ids=["member-two"], properties={"email": "second@example.com", "plan": "free"}
        )
        create_person(team=self.team, distinct_ids=["non-member"], properties={"email": "outside@example.com"})
        flush_persons_and_events()
        self._insert_membership("member-one", "2024-01-01", "2024-01-05")
        self._insert_membership("member-one-alias", "2024-01-02", "2024-01-09")
        self._insert_membership("member-two", "2024-01-03", "2024-01-06")
        self._insert_membership("non-member", "2024-01-01", "2024-01-10", group_key="another-workspace")
        self._insert_membership("non-member", "2024-01-01", "2024-01-10", group_type_index=1)
        self._insert_membership(
            "non-member", "2024-01-01", "2024-01-10", team_id=Team.objects.create(organization=self.organization).pk
        )

    def _get_widget_query(self, **overrides: Any) -> dict[str, Any]:
        return {
            "kind": "ActorsQuery",
            "source": {"kind": "AccountUsersQuery", "accountId": str(self.account.id)},
            "select": ["person_display_name -- Person", "properties.plan", "source.account_last_seen"],
            "orderBy": ["source.account_last_seen DESC"],
            **overrides,
        }

    def _run_widget_query(self, **overrides: Any) -> Any:
        return self.client.post(
            self.endpoint,
            {"query": self._get_widget_query(**overrides), "refresh": "blocking"},
            format="json",
        )

    @parameterized.expand([False, True])
    def test_widget_query_supports_display_names_filters_search_sort_and_pages(self, materialized_cte: bool) -> None:
        self.enterContext(self.settings(HOGQL_MATERIALIZED_CTE_SUPPORTED=materialized_cte))
        with patch("posthog.hogql_queries.paginators.execute_hogql_query", wraps=execute_hogql_query) as execute_query:
            response = self._run_widget_query(limit=1)
        assert execute_query.call_args.kwargs["settings"].max_threads == 120
        assert response.status_code == 200, response.content
        page = response.json()
        assert page["results"][0][0] == {"display_name": "first@example.com", "id": str(self.first.uuid)}
        assert page["hasMore"] and page["limit"] == 1
        runner = get_query_runner(self._get_widget_query(limit=1), self.team, user=self.user)
        assert isinstance(runner, ActorsQueryRunner)
        query = runner.paginator.paginate(runner.to_query())
        context = runner.build_hogql_context(enable_select_queries=True, modifiers=runner.modifiers)
        sql, _ = prepare_and_print_ast(
            query,
            context=context,
            dialect="clickhouse",
        )
        self.assertQueryMatchesSnapshot(sql)
        plan = json.loads(sync_execute("EXPLAIN PLAN indexes=1, json=1 " + sql, context.values)[0][0])
        pending = [plan[0]["Plan"]]
        person_reads = []
        while pending:
            step = pending.pop()
            if step["Node Type"] == "ReadFromMergeTree" and step.get("Description", "").endswith(".person"):
                person_reads.append(step)
            pending.extend(step.get("Plans", []))
        assert person_reads
        assert all(
            any(
                index["Type"] == "PrimaryKey" and "(id in " in index.get("Condition", "")
                for index in step.get("Indexes", [])
            )
            for step in person_reads
        )
        response = self._run_widget_query(limit=1, offset=1)
        assert response.status_code == 200, response.content
        assert response.json()["results"][0][0]["id"] == str(self.second.uuid)
        response = self._run_widget_query(
            search="member-one-alias",
            properties=[{"type": "person", "key": "plan", "operator": "exact", "value": "paid"}],
            orderBy=["properties.plan ASC"],
        )
        assert response.status_code == 200, response.content
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0][0]["id"] == str(self.first.uuid)

    @parameterized.expand([("flag_disabled",), ("account_hidden",)])
    def test_widget_cached_results_repeat_access_checks(self, condition: str) -> None:
        response = self._run_widget_query()
        assert response.status_code == 200, response.content
        if condition == "account_hidden":
            self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
            self.organization.save()
            AccessControl.objects.create(
                team=self.team,
                resource="account",
                resource_id=str(self.account.id),
                access_level="none",
                organization_member=self.organization_membership,
            )
        with patch(FLAG_CHECK, return_value=condition != "flag_disabled"):
            response = self.client.post(self.endpoint, {"query": self._get_widget_query()}, format="json")
        assert response.status_code == 400, response.content

    @parameterized.expand(
        [
            ("no_user",),
            ("different_user",),
            ("person_properties",),
            ("event_properties",),
            ("group_properties",),
            ("resource_access",),
        ]
    )
    def test_widget_cache_read_requires_the_same_authorization_context(self, condition: str) -> None:
        if condition.endswith("properties"):
            self.organization.available_product_features = [{"key": AvailableFeature.PROPERTY_ACCESS_CONTROL}]
            self.organization.save()
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
        elif condition == "resource_access":
            self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
            self.organization.save()
        get_query_runner(self._get_widget_query(), self.team, user=self.user).run(
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user
        )
        user: User | None = self.user
        if condition == "no_user":
            user = None
        elif condition == "different_user":
            user = User.objects.create_and_join(self.organization, "reader@example.com", password=None)
        elif condition == "resource_access":
            AccessControl.objects.create(
                team=self.team,
                resource="dashboard",
                access_level="none",
                organization_member=self.organization_membership,
            )
        else:
            property_type = {
                "person_properties": PropertyDefinition.Type.PERSON,
                "event_properties": PropertyDefinition.Type.EVENT,
                "group_properties": PropertyDefinition.Type.GROUP,
            }[condition]
            self._restrict_properties(property_type)
        response = get_query_runner(self._get_widget_query(), self.team, user=user).run(
            ExecutionMode.CACHE_ONLY_NEVER_CALCULATE, user=user
        )
        assert isinstance(response, CacheMissResponse)

    def test_widget_display_name_and_search_hide_restricted_properties(self) -> None:
        self._restrict_properties()
        response = self._run_widget_query()
        assert response.status_code == 200, response.content
        assert all(row[0]["display_name"] == row[0]["id"] for row in response.json()["results"])
        response = self._run_widget_query(search="first@example.com")
        assert response.status_code == 200, response.content
        assert response.json()["results"] == []

    @parameterized.expand([([],), (["person"],), (["actor"],)])
    def test_widget_cannot_request_raw_person_objects(self, columns: list[str]) -> None:
        assert self._run_widget_query(select=columns).status_code == 400

    @parameterized.expand(
        [
            (refresh, interface)
            for refresh in ("async", "force_async", "async_except_on_cache_miss", "lazy_async", "legacy")
            for interface in ("generic", "wrapped")
        ]
    )
    def test_async_account_user_requests_are_rejected(self, refresh: str, interface: str) -> None:
        query = self._get_widget_query()
        data: dict[str, Any] = {
            "query": {"kind": "DataTableNode", "source": query} if interface == "wrapped" else query
        }
        if refresh == "legacy":
            data["async"] = True
        else:
            data["refresh"] = refresh
        endpoint = self.endpoint
        with patch("posthog.hogql_queries.query_runner.enqueue_process_query_task") as enqueue:
            response = self.client.post(endpoint, data, format="json")
        assert response.status_code == 400, response.content
        enqueue.assert_not_called()

    @parameterized.expand([(True, 403), (False, 200)])
    def test_account_user_query_ids_are_unavailable(self, account_users: bool, expected: int) -> None:
        stored = QueryStatus(
            id="stored-query",
            team_id=self.team.pk,
            complete=True,
            labels=[f"customer-analytics-account-users:{self.account.id}"] if account_users else [],
            results={"results": [["member"]]},
        )
        with patch("posthog.api.query.get_query_status", return_value=stored):
            response = self.client.get(f"/api/projects/{self.team.pk}/query/stored-query/")
        assert response.status_code == expected, response.content

    def _insert_membership(
        self,
        distinct_id: str,
        first_seen: str,
        last_seen: str,
        *,
        group_key: str = "workspace-demo",
        group_type_index: int = 0,
        team_id: int | None = None,
    ) -> None:
        sync_execute(
            "INSERT INTO person_group_membership (team_id, group_type_index, group_key, distinct_id, first_seen, last_seen) VALUES",
            [
                {
                    "team_id": self.team.pk if team_id is None else team_id,
                    "group_type_index": group_type_index,
                    "group_key": group_key,
                    "distinct_id": distinct_id,
                    "first_seen": datetime.fromisoformat(first_seen).replace(tzinfo=UTC),
                    "last_seen": datetime.fromisoformat(last_seen).replace(tzinfo=UTC),
                }
            ],
        )

    @parameterized.expand(
        [(side, interface) for side in ("mapping", "person") for interface in ("widget", "membership")]
    )
    def test_deleted_identity_is_not_returned(self, deleted_side: str, interface: str) -> None:
        if deleted_side == "mapping":
            sync_execute(
                "INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version) VALUES",
                [
                    {
                        "team_id": self.team.pk,
                        "distinct_id": "member-two",
                        "person_id": self.second.uuid,
                        "is_deleted": 1,
                        "version": 100,
                    }
                ],
            )
        else:
            sync_execute(
                "INSERT INTO person (team_id, id, properties, is_identified, is_deleted, version, created_at) VALUES",
                [
                    {
                        "team_id": self.team.pk,
                        "id": self.second.uuid,
                        "properties": "{}",
                        "is_identified": 1,
                        "is_deleted": 1,
                        "version": 100,
                        "created_at": datetime(2024, 1, 1, tzinfo=UTC),
                    }
                ],
            )
        columns = ["persons.id"] if interface == "widget" else ["source.distinct_ids"]
        response = self._run_widget_query(select=columns, limit=1)
        assert response.status_code == 200, response.content
        page = response.json()
        assert len(page["results"]) == 1
        assert not page["hasMore"]
        if interface == "widget":
            assert page["results"][0][0] == str(self.first.uuid)
        else:
            assert set(page["results"][0][0]) == {"member-one", "member-one-alias"}

    @parameterized.expand(
        [
            ("query_account_only", ["query:read", "account:read"], 403, "query"),
            ("query_person_only", ["query:read", "person:read"], 403, "query"),
            ("query_both", ["query:read", "account:read", "person:read"], 200, "query"),
        ]
    )
    def test_tokens_require_both_scopes(self, _name: str, scopes: list[str], expected: int, interface: str) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="account persons", user=self.user, secure_value=hash_key_value(token), scopes=scopes
        )
        self.client.logout()
        headers = {"authorization": f"Bearer {token}"}
        response = self.client.post(
            self.endpoint,
            {"query": self._get_widget_query(), "refresh": "blocking"},
            format="json",
            headers=headers,
        )
        assert response.status_code == expected, response.content

    def _restrict_properties(self, property_type: int = PropertyDefinition.Type.PERSON) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.PROPERTY_ACCESS_CONTROL}]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        for name in ["email", "name", "private_note"]:
            definition = PropertyDefinition.objects.create(
                team=self.team,
                name=name,
                type=property_type,
                group_type_index=0 if property_type == PropertyDefinition.Type.GROUP else None,
            )
            PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")
