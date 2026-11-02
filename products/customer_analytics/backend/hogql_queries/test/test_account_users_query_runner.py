from posthog.test.base import APIBaseTest, ClickhouseTestMixin, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.schema import CacheMissResponse, QueryStatus

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.models import Organization, OrganizationMembership, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.persons import create_person

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.constants import ACCOUNT_USERS_QUERY_STATUS_LABEL_PREFIX
from products.customer_analytics.backend.logic.account_member_search import list_organization_member_distinct_ids
from products.customer_analytics.backend.test.factories import create_account

FLAG_CHECK = "products.customer_analytics.backend.logic.account_member_search.posthog_feature_flag_enabled"


class TestAccountUsersQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        customer_org = Organization.objects.create(name="Customer")
        for email in ("ana@example.com", "bo@example.com"):
            member = User.objects.create(email=email, distinct_id=f"distinct-{email}")
            OrganizationMembership.objects.create(organization=customer_org, user=member)
            create_person(team=self.team, distinct_ids=[member.distinct_id], properties={"email": email})
        create_person(team=self.team, distinct_ids=["outsider"], properties={"email": "outsider@example.com"})
        flush_persons_and_events()
        self.account = create_account(team_id=self.team.id, external_id=str(customer_org.id))
        self.query = {
            "kind": "ActorsQuery",
            "source": {"kind": "AccountUsersQuery", "accountId": str(self.account.id)},
            "select": ["properties.email"],
            "orderBy": ["properties.email DESC"],
        }
        self.user.is_staff = True
        self.user.save()

    def _run(self, headers: dict[str, str] | None = None):
        return self.client.post(
            f"/api/projects/{self.team.id}/query/",
            {"query": self.query, "refresh": "blocking"},
            format="json",
            headers=headers,
        )

    def _hide_account_from_user(self) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

    @patch(FLAG_CHECK, return_value=True)
    def test_staff_get_the_organization_members_as_persons(self, _flag) -> None:
        response = self._run()

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["results"] == [["bo@example.com"], ["ana@example.com"]]

    @parameterized.expand(
        [
            ("not_staff", False, True, False),
            ("flag_off", True, False, False),
            ("account_hidden", True, True, True),
        ]
    )
    def test_denies_access_even_when_cached(self, _name, is_staff, flag_on, account_hidden) -> None:
        with patch(FLAG_CHECK, return_value=True):
            assert self._run().status_code == status.HTTP_200_OK

        self.user.is_staff = is_staff
        self.user.save()
        if account_hidden:
            self._hide_account_from_user()
        with patch(FLAG_CHECK, return_value=flag_on):
            response = self._run()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "Access control failure" in response.json()["detail"]

    @patch(FLAG_CHECK, return_value=True)
    def test_cache_only_read_without_a_user_misses_staff_results(self, _flag) -> None:
        get_query_runner(self.query, self.team, user=self.user).run(
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user
        )

        response = get_query_runner(self.query, self.team).run(ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)

        assert isinstance(response, CacheMissResponse)

    @parameterized.expand([("staff", True, status.HTTP_200_OK), ("not_staff", False, status.HTTP_403_FORBIDDEN)])
    @patch(FLAG_CHECK, return_value=True)
    def test_async_result_retrieval_repeats_the_access_check(self, _name, is_staff, expected_status, _flag) -> None:
        self.user.is_staff = is_staff
        self.user.save()
        stored = QueryStatus(
            id="account-users-query",
            team_id=self.team.id,
            complete=True,
            labels=[f"{ACCOUNT_USERS_QUERY_STATUS_LABEL_PREFIX}{self.account.id}"],
            results={"results": [["ana@example.com"]]},
        )

        with patch("posthog.api.query.get_query_status", return_value=stored):
            response = self.client.get(f"/api/projects/{self.team.id}/query/account-users-query/")

        assert response.status_code == expected_status, response.content

    @parameterized.expand(
        [
            ("query_scope_only", ["query:read"], status.HTTP_403_FORBIDDEN),
            ("all_scopes", ["query:read", "account:read", "person:read"], status.HTTP_200_OK),
        ]
    )
    @patch(FLAG_CHECK, return_value=True)
    def test_api_tokens_need_account_and_person_scopes(self, _name, scopes, expected_status, _flag) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="account users query",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=scopes,
            scoped_teams=[],
            scoped_organizations=[],
        )

        response = self._run(headers={"authorization": f"Bearer {token}"})

        assert response.status_code == expected_status, response.content

    def test_eu_lookup_failure_raises_instead_of_returning_no_members(self) -> None:
        with (
            patch(
                "products.customer_analytics.backend.logic.account_member_search.execute_hogql_query",
                side_effect=TimeoutError("eu lookup timed out"),
            ),
            self.assertRaises(TimeoutError),
        ):
            list_organization_member_distinct_ids(
                team=self.team, user=self.user, organization_id=str(Organization.objects.create(name="EU").id)
            )
