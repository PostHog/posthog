from __future__ import annotations

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from ee.billing.quota_limiting import (
    QuotaLimitingCaches,
    QuotaResource,
    add_limited_team_tokens,
    replace_limited_team_tokens,
)


def _clear_ai_credits_limits() -> None:
    replace_limited_team_tokens(QuotaResource.AI_CREDITS, {}, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


class TestQuotaLimitsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _clear_ai_credits_limits()

    def tearDown(self) -> None:
        _clear_ai_credits_limits()
        super().tearDown()

    def _url(self, team_id: int | None = None) -> str:
        return f"/api/projects/{team_id if team_id is not None else self.team.pk}/quota_limits/"

    def _set_ai_credits_limit(self, team_api_token: str, expires_at: int) -> None:
        add_limited_team_tokens(
            QuotaResource.AI_CREDITS,
            {team_api_token: expires_at},
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
        )

    def test_unauthenticated_returns_401_or_403(self) -> None:
        self.client.logout()
        response = self.client.get(self._url())
        # DRF returns 401 when no creds are presented and an authenticator that supports
        # a WWW-Authenticate challenge is configured; otherwise it returns 403. Either is
        # an auth failure — we only care that the endpoint refuses unauthenticated reads.
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_session_auth_returns_under_quota_when_team_not_limited(self) -> None:
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["limited"]["ai_credits"], {"limited": False})

    def test_returns_limited_when_team_is_over_quota(self) -> None:
        self._set_ai_credits_limit(self.team.api_token, 9_999_999_999)

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["limited"]["ai_credits"], {"limited": True})

    def test_returns_unlimited_when_limit_has_already_expired(self) -> None:
        self._set_ai_credits_limit(self.team.api_token, 1)  # epoch 1970

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["limited"]["ai_credits"], {"limited": False})

    def test_personal_api_key_auth_works(self) -> None:
        self.client.logout()
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="quota_limits-test",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["project:read"],
        )

        self._set_ai_credits_limit(self.team.api_token, 9_999_999_999)

        response = self.client.get(
            self._url(),
            headers={"authorization": f"Bearer {raw_key}"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["limited"]["ai_credits"], {"limited": True})

    def test_user_not_in_teams_org_is_forbidden(self) -> None:
        other_org = Organization.objects.create(name="other-org")
        other_team = Team.objects.create(organization=other_org, name="other-team")

        response = self.client.get(self._url(other_team.pk))
        # The caller is logged in to a team in a different org — TeamMemberAccessPermission
        # rejects with 403 (or 404 if the queryset can't see the team at all).
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_personal_api_key_scoped_to_a_different_team_is_forbidden(self) -> None:
        # Caller has access to both teams via membership, but the token is scoped to
        # `other_team` only — the standalone-endpoint design would have missed this and
        # leaked the other team's state.
        other_team = Team.objects.create(organization=self.organization, name="other-team")
        self.client.logout()
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="quota_limits-test",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["project:read"],
            scoped_teams=[other_team.pk],
        )

        response = self.client.get(
            self._url(),
            headers={"authorization": f"Bearer {raw_key}"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_personal_api_key_missing_required_scope_is_forbidden(self) -> None:
        # A token with only `feature_flag:read` shouldn't be able to read quota state.
        self.client.logout()
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="quota_limits-test",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["feature_flag:read"],
        )

        response = self.client.get(
            self._url(),
            headers={"authorization": f"Bearer {raw_key}"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_response_includes_every_quota_resource(self) -> None:
        # Limiting one resource must not hide the unlimited state of the rest.
        self._set_ai_credits_limit(self.team.api_token, 9_999_999_999)

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        limited = response.json()["limited"]
        expected_keys = {resource.value for resource in QuotaResource}
        self.assertEqual(set(limited.keys()), expected_keys)
        self.assertTrue(limited["ai_credits"]["limited"])
        for resource in QuotaResource:
            if resource is QuotaResource.AI_CREDITS:
                continue
            self.assertFalse(limited[resource.value]["limited"], resource.value)

    def test_multi_team_user_gets_per_team_answers(self) -> None:
        # Same user belongs to two teams in their org; each team's quota is independent.
        # This is the regression that "me" couldn't model — `user.team` (current team)
        # picked one arbitrary answer for users in multiple teams.
        other_team = Team.objects.create(organization=self.organization, name="other-team")
        self._set_ai_credits_limit(self.team.api_token, 9_999_999_999)
        # other_team's token deliberately not limited

        resp_self = self.client.get(self._url())
        resp_other = self.client.get(self._url(other_team.pk))

        self.assertEqual(resp_self.json()["limited"]["ai_credits"], {"limited": True})
        self.assertEqual(resp_other.json()["limited"]["ai_credits"], {"limited": False})
