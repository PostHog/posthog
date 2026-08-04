import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team import Team
from posthog.models.utils import hash_key_value
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.persons import create_person

_UNSET = object()


def _make_psak(team, label="psak", scopes=_UNSET):
    suffix = "".join(c for c in label if c.isalnum())
    token = "phs_" + ("a" * 35) + suffix
    psak = ProjectSecretAPIKey.objects.create(
        team=team,
        label=label,
        mask_value=f"phs_...{suffix[:4]}",
        secure_value=hash_key_value(token),
        scopes=["session_recording:read"] if scopes is _UNSET else scopes,
    )
    return token, psak


class TestSessionRecordingViewSetPSAKAuth(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.session_id = "psak-auth-session"
        create_person(team=self.team, distinct_ids=["u1"], properties={"email": "bob@bob.com"})
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        produce_replay_summary(
            session_id=self.session_id,
            team_id=self.team.pk,
            first_timestamp=base_time.isoformat(),
            last_timestamp=base_time.isoformat(),
            distinct_id="u1",
        )
        # Log out the test client so only the PSAK header authenticates requests.
        self.client.logout()

    def _auth_headers(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_psak_can_list_recordings(self):
        token, _ = _make_psak(self.team, label="list-key")

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_psak_can_retrieve_recording(self):
        token, _ = _make_psak(self.team, label="retrieve-key")

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{self.session_id}",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    @parameterized.expand(
        [
            ("update", "PATCH", "", {"viewed": True}),
            ("viewed", "GET", "/viewed", None),
            ("matching_events", "GET", "", None),
        ]
    )
    def test_psak_blocked_on_non_read_actions(self, name, method, detail_path_suffix, body):
        token, _ = _make_psak(self.team, label=f"blocked-{name}")
        path = (
            f"/api/projects/{self.team.id}/session_recordings/matching_events"
            if name == "matching_events"
            else f"/api/projects/{self.team.id}/session_recordings/{self.session_id}{detail_path_suffix}"
        )
        kwargs = self._auth_headers(token)
        if body is not None:
            kwargs["content_type"] = "application/json"

        response = self.client.generic(
            method,
            path,
            data=json.dumps(body) if body is not None else "",
            **kwargs,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertIn("does not support project secret API key", response.json().get("detail", ""))

    @parameterized.expand(
        [
            ("empty_list", []),
            ("null", None),
        ]
    )
    def test_psak_without_session_recording_scope_returns_403(self, _name, scopes):
        token, _ = _make_psak(self.team, label=f"no-scope-{_name}", scopes=scopes)

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{self.session_id}",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertIn("missing required scope 'session_recording:read'", response.json().get("detail", ""))

    def test_unknown_psak_returns_401(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{self.session_id}",
            **self._auth_headers("phs_" + "z" * 35),
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.content)

    def test_psak_team_mismatch_returns_403(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        token, _ = _make_psak(self.team, label="team-mismatch-key")

        response = self.client.get(
            f"/api/projects/{other_team.id}/session_recordings/{self.session_id}",
            **self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    def test_session_auth_still_works_on_viewset(self):
        # Regression: wiring PSAK into authentication_classes must not break session auth.
        self.client.force_login(self.user)

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


@patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
@patch("posthog.session_recordings.session_recording_api.ReplayBurstRateThrottle.rate", new="2/minute")
class TestSessionRecordingPSAKRateLimit(ClickhouseTestMixin, APIBaseTest):
    """Regression coverage for the bug this PSAK wiring fixes: before it, PersonalApiKeyRateThrottle
    subclasses treat any authenticated, non-personal-key request as exempt, so PSAK traffic sailed
    through every throttle on this viewset uncounted."""

    def setUp(self):
        super().setUp()
        self.session_id = "psak-rl-session"
        create_person(team=self.team, distinct_ids=["u1"], properties={"email": "bob@bob.com"})
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        produce_replay_summary(
            session_id=self.session_id,
            team_id=self.team.pk,
            first_timestamp=base_time.isoformat(),
            last_timestamp=base_time.isoformat(),
            distinct_id="u1",
        )
        self.client.logout()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _retrieve(self, token=None):
        url = f"/api/projects/{self.team.id}/session_recordings/{self.session_id}"
        if token is None:
            return self.client.get(url)
        return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_psak_requests_are_throttled(self, *_args):
        token, _ = _make_psak(self.team, label="rl-key")

        for _ in range(2):
            self.assertEqual(self._retrieve(token).status_code, status.HTTP_200_OK)

        self.assertEqual(self._retrieve(token).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_distinct_psak_keys_get_independent_buckets(self, *_args):
        token_a, _a = _make_psak(self.team, label="key-a")
        token_b, _b = _make_psak(self.team, label="key-b")

        for _ in range(2):
            self.assertEqual(self._retrieve(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._retrieve(token_a).status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(self._retrieve(token_b).status_code, status.HTTP_200_OK)

    @patch(
        "posthog.session_recordings.session_recording_api.ReplayPSAKTeamBurstRateThrottle.rate",
        new="3/minute",
    )
    def test_distinct_psak_keys_share_project_bucket(self, *_args):
        token_a, _a = _make_psak(self.team, label="team-key-a")
        token_b, _b = _make_psak(self.team, label="team-key-b")

        self.assertEqual(self._retrieve(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._retrieve(token_a).status_code, status.HTTP_200_OK)
        self.assertEqual(self._retrieve(token_b).status_code, status.HTTP_200_OK)
        self.assertEqual(self._retrieve(token_b).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_session_user_is_not_throttled(self, *_args):
        self.client.force_login(self.user)

        for _ in range(4):
            self.assertEqual(self._retrieve().status_code, status.HTTP_200_OK)
