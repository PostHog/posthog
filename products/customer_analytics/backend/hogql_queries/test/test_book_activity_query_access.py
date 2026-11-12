from typing import Any

import pytest
import time_machine
from posthog.test.base import flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import QueryStatus

from posthog.api.services.query import ExecutionMode, process_query_dict
from posthog.clickhouse.query_tagging import reset_query_tags
from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import OrganizationMembership, PersonalAPIKey
from posthog.models.group_usage_metric import GroupUsageMetric
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.customer_analytics.backend.constants import ACTIVITY_QUERY_PROPERTY_ACCESS_LABEL_PREFIX
from products.customer_analytics.backend.facade.api import validate_book_activity_people_access
from products.customer_analytics.backend.hogql_queries.test.book_activity_test_case import ANA, BookActivityTestCase
from products.event_definitions.backend.models import PropertyDefinition

KINDS = [("BookActivityMatrixQuery",), ("BookActivityPeopleQuery",), ("BookActivityFirstsQuery",)]


@time_machine.travel("2026-10-28T18:00:00Z", tick=False)
class TestBookActivityQueryAccess(BookActivityTestCase):
    def _query(self, kind: str) -> dict[str, Any]:
        if kind == "AccountActivityMatrixQuery":
            return {"kind": kind, "accountId": str(self.alpha.id)}
        query: dict[str, Any] = {"kind": kind, "accountIds": [str(self.alpha.id), str(self.beta.id)]}
        if kind != "BookActivityFirstsQuery":
            query.update(dateRange={"date_from": "-4w"}, interval="week")
        return query

    def test_people_status_rejects_missing_user(self) -> None:
        with pytest.raises(UserAccessControlError):
            validate_book_activity_people_access(self.team, None, str(self.user.id))

    @parameterized.expand(KINDS)
    def test_owner_bound_jobs_have_distinct_cache_keys(self, kind: str) -> None:
        query = self._query(kind)
        first = get_query_runner(query, self.team, user=self.user)
        second = get_query_runner(query, self.team, user=self.other_user)
        assert first.get_cache_key() != second.get_cache_key()

    @parameterized.expand(
        [
            (kind, interval, date_from, date_to, expected)
            for kind in ("BookActivityMatrixQuery", "BookActivityPeopleQuery")
            for interval, date_from, date_to, expected in (
                ("week", "2020-01-05", "2021-12-26", 200),
                ("week", "2020-01-05", "2022-01-02", 400),
                ("month", "2020-01-01", "2028-08-01", 200),
                ("month", "2020-01-01", "2028-09-01", 400),
                ("week", "1900-01-01", "2100-01-01", 400),
                ("month", "1900-01-01", "2100-01-01", 400),
            )
        ]
    )
    def test_period_count_is_bounded_before_building_columns(
        self, kind: str, interval: str, date_from: str, date_to: str, expected: int
    ) -> None:
        query = {
            "kind": kind,
            "accountIds": [],
            "interval": interval,
            "dateRange": {"date_from": date_from, "date_to": date_to},
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/query/", {"query": query, "refresh": "blocking"}, format="json"
        )
        assert response.status_code == expected, response.content
        if expected == 200:
            assert len(response.json()["results"]["columns"]) == 104
        else:
            assert "104 periods" in response.json()["detail"]

    @parameterized.expand(KINDS)
    def test_untagged_queries_run_with_rate_limits(self, kind: str) -> None:
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        flush_persons_and_events()
        reset_query_tags()
        self.addCleanup(reset_query_tags)
        with patch("posthog.clickhouse.client.limit.TEST", False):
            response = self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {"query": self._query(kind), "refresh": "blocking"},
                format="json",
            )
        assert response.status_code == 200, response.content
        assert response.json()["results"]["rows"]

    @parameterized.expand(KINDS)
    def test_flag_revocation_blocks_cached_results_and_async_status(self, kind: str) -> None:
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        flush_persons_and_events()
        query = self._query(kind)
        url = f"/api/projects/{self.team.id}/query/"
        first = self.client.post(url, {"query": query, "refresh": "blocking"}, format="json")
        assert first.status_code == 200, first.content
        labels = get_query_runner(query, self.team, user=self.user).query_status_labels()
        stored = QueryStatus(
            id="book-activity", team_id=self.team.id, complete=True, labels=labels, results=first.json()
        )
        with patch("posthog.api.query.get_query_status", return_value=stored):
            assert self.client.get(url + "book-activity/").status_code == 200
            self.flag_enabled = False
            denied = self.client.get(url + "book-activity/")
            assert denied.status_code == 403, denied.content
            assert "results" not in denied.json()
        denied_cached = self.client.post(url, {"query": query, "refresh": "force_cache"}, format="json")
        assert denied_cached.status_code == 400, denied_cached.content
        assert "results" not in denied_cached.json()

    @parameterized.expand([(kind, limit) for (kind,) in KINDS for limit in (None, 1)])
    def test_async_status_rechecks_every_account(self, kind: str, limit: int | None) -> None:
        query = {**self._query(kind), "rowLimit": limit}
        stored = QueryStatus(
            id="book-activity",
            team_id=self.team.id,
            complete=True,
            labels=get_query_runner(query, self.team, user=self.user).query_status_labels(),
        )
        self.beta.name = "Aardvark"
        self.beta.save(update_fields=["name"])
        result = process_query_dict(
            self.team,
            query,
            user=self.user,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            query_status=stored,
        )
        stored.results = result if isinstance(result, dict) else result.model_dump()
        assert stored.results["results"]["rows"][0]["key"] == str(self.beta.id)
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.beta.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )
        with patch("posthog.api.query.get_query_status", return_value=stored):
            response = self.client.get(f"/api/projects/{self.team.id}/query/book-activity/")
        assert response.status_code == 403, response.content

    @parameterized.expand(
        [
            ("BookActivityPeopleQuery", False, PropertyDefinition.Type.PERSON),
            ("BookActivityFirstsQuery", False, PropertyDefinition.Type.PERSON),
            ("AccountActivityMatrixQuery", False, PropertyDefinition.Type.PERSON),
            ("AccountActivityMatrixQuery", True, PropertyDefinition.Type.PERSON),
            ("AccountActivityMatrixQuery", True, PropertyDefinition.Type.EVENT),
        ]
    )
    def test_async_status_rechecks_property_access(self, kind: str, other_reader: bool, property_type: int) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.PROPERTY_ACCESS_CONTROL}]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="Activity",
            filters={"events": [{"id": "insight created", "type": "events"}]},
            math=GroupUsageMetric.Math.SUM,
            math_property="private_value",
        )
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha, properties={"private_value": 5})
        flush_persons_and_events()
        stored = QueryStatus(id="activity", team_id=self.team.id, complete=True)
        result = process_query_dict(
            self.team,
            self._query(kind),
            user=self.user,
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            query_status=stored,
        )
        stored.results = result if isinstance(result, dict) else result.model_dump()
        assert stored.results["results"]["rows"]
        reader = self.other_user if other_reader else self.user
        definition = PropertyDefinition.objects.create(
            team=self.team,
            name="email" if property_type == PropertyDefinition.Type.PERSON else "private_value",
            type=property_type,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=OrganizationMembership.objects.get(user=reader, organization=self.organization),
            access_level="none",
        )
        self.client.force_login(reader)
        with patch("posthog.api.query.get_query_status", return_value=stored):
            response = self.client.get(f"/api/projects/{self.team.id}/query/activity/")
        assert response.status_code == 403, response.content
        assert "results" not in response.json()

    def test_async_status_rejects_missing_property_access_snapshot(self) -> None:
        labels = get_query_runner(
            self._query("BookActivityPeopleQuery"), self.team, user=self.user
        ).query_status_labels()
        assert labels is not None
        stored = QueryStatus(
            id="activity",
            team_id=self.team.id,
            complete=True,
            labels=[label for label in labels if not label.startswith(ACTIVITY_QUERY_PROPERTY_ACCESS_LABEL_PREFIX)],
            results={"results": {"people": [{"label": "person@example.com"}]}},
        )
        with patch("posthog.api.query.get_query_status", return_value=stored):
            response = self.client.get(f"/api/projects/{self.team.id}/query/activity/")
        assert response.status_code == 403, response.content

    @parameterized.expand([("BookActivityPeopleQuery",), ("BookActivityFirstsQuery",)])
    def test_people_queries_exclude_hidden_accounts(self, kind: str) -> None:
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.beta)
        flush_persons_and_events()
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.alpha.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/query/", {"query": self._query(kind), "refresh": "blocking"}, format="json"
        )
        assert response.status_code == 200, response.content
        assert [row["key"] for row in response.json()["results"]["rows"]] == [str(self.beta.id)]
        assert {person["row"] for person in response.json()["results"]["people"]} == {str(self.beta.id)}

    @parameterized.expand(
        [
            ("AccountActivityMatrixQuery", ["query:read"], 403),
            ("AccountActivityMatrixQuery", ["query:read", "account:read"], 403),
            ("AccountActivityMatrixQuery", ["query:read", "person:read"], 403),
            ("AccountActivityMatrixQuery", ["query:read", "account:read", "person:read"], 200),
            ("AccountActivityMatrixQuery", ["*"], 200),
            ("BookActivityMatrixQuery", ["query:read"], 403),
            ("BookActivityMatrixQuery", ["query:read", "account:read"], 200),
            ("BookActivityPeopleQuery", ["query:read", "account:read"], 403),
            ("BookActivityPeopleQuery", ["query:read", "account:read", "person:read"], 200),
            ("BookActivityFirstsQuery", ["query:read", "account:read"], 403),
            ("BookActivityFirstsQuery", ["query:read", "account:read", "person:read"], 200),
            ("BookActivityMatrixQuery", ["*"], 200),
            ("BookActivityPeopleQuery", ["*"], 200),
            ("BookActivityFirstsQuery", ["*"], 200),
        ]
    )
    def test_async_status_requires_the_same_token_scopes_as_execution(
        self, kind: str, scopes: list[str], expected: int
    ) -> None:
        labels = get_query_runner(self._query(kind), self.team, user=self.user).query_status_labels()
        stored = QueryStatus(
            id="book-activity",
            team_id=self.team.id,
            complete=True,
            labels=labels,
            results={"results": {"people": [{"label": "user@example.com"}]}},
        )
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="book query",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=scopes,
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        with patch("posthog.api.query.get_query_status", return_value=stored):
            response = self.client.get(
                f"/api/projects/{self.team.id}/query/book-activity/", headers={"Authorization": f"Bearer {token}"}
            )
        assert response.status_code == expected, response.content

    @parameterized.expand(KINDS)
    def test_runner_rechecks_accounts_when_its_user_changes(self, kind: str) -> None:
        runner = get_query_runner(self._query(kind), self.team, user=self.user)
        assert [row.key for row in runner.calculate().results.rows] == [str(self.alpha.id), str(self.beta.id)]
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.alpha.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(
                user=self.other_user, organization=self.organization
            ),
        )
        runner.set_user(self.other_user)
        assert [row.key for row in runner.calculate().results.rows] == [str(self.beta.id)]
