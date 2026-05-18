from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import PulseDigest, PulseFinding, PulseSubscription
from posthog.models.pulse import PulseDigestStatus, PulseFindingFeedback


def _make_digest(team) -> PulseDigest:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    return PulseDigest.objects.create(
        team=team,
        period_start=now - timedelta(days=7),
        period_end=now,
        status=PulseDigestStatus.DELIVERED,
    )


def _make_finding(digest, label: str = "Test metric", rank: int = 0) -> PulseFinding:
    return PulseFinding.objects.create(
        digest=digest,
        metric_descriptor={"source": "top_event", "label": label, "query": {}},
        metric_label=label,
        current_value=100.0,
        baseline_value=80.0,
        change_pct=0.25,
        z_score=2.5,
        narrative=f"{label} rose 25%.",
        rank=rank,
    )


class TestPulseAPI(APIBaseTest):
    def test_list_digests_returns_only_current_team(self) -> None:
        _make_digest(self.team)
        other_team_digest = _make_digest(self.organization.teams.create(name="other"))
        response = self.client.get(f"/api/environments/{self.team.id}/pulse_digests/")
        assert response.status_code == status.HTTP_200_OK
        ids = [d["id"] for d in response.json()["results"]]
        assert str(other_team_digest.id) not in ids

    def test_list_digests_includes_finding_count(self) -> None:
        digest = _make_digest(self.team)
        _make_finding(digest)
        _make_finding(digest, label="Metric B", rank=1)
        response = self.client.get(f"/api/environments/{self.team.id}/pulse_digests/")
        body = response.json()
        assert body["results"][0]["finding_count"] == 2

    def test_retrieve_digest_returns_findings(self) -> None:
        digest = _make_digest(self.team)
        _make_finding(digest)
        response = self.client.get(f"/api/environments/{self.team.id}/pulse_digests/{digest.id}/")
        body = response.json()
        assert body["finding_count"] == 1
        assert len(body["findings"]) == 1

    def test_list_findings_filters_by_team_via_digest(self) -> None:
        digest = _make_digest(self.team)
        _make_finding(digest)
        other_team = self.organization.teams.create(name="other")
        other_digest = _make_digest(other_team)
        _make_finding(other_digest, label="Other team finding")

        response = self.client.get(f"/api/environments/{self.team.id}/pulse_findings/")
        labels = [f["metric_label"] for f in response.json()["results"]]
        assert labels == ["Test metric"]

    def test_submit_feedback(self) -> None:
        digest = _make_digest(self.team)
        finding = _make_finding(digest)
        response = self.client.post(
            f"/api/environments/{self.team.id}/pulse_findings/{finding.id}/feedback/",
            {"action": "up"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        finding.refresh_from_db()
        assert finding.feedback == PulseFindingFeedback.THUMBS_UP
        assert finding.feedback_user_id == self.user.id
        assert finding.feedback_at is not None

    def test_submit_feedback_rejects_invalid_action(self) -> None:
        digest = _make_digest(self.team)
        finding = _make_finding(digest)
        response = self.client.post(
            f"/api/environments/{self.team.id}/pulse_findings/{finding.id}/feedback/",
            {"action": "garbage"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_subscription_current_returns_defaults_when_missing(self) -> None:
        response = self.client.get(f"/api/environments/{self.team.id}/pulse_subscriptions/current/")
        body = response.json()
        assert body["id"] is None
        assert body["enabled"] is False
        assert body["frequency"] == "weekly"

    def test_subscription_create_then_update(self) -> None:
        create_resp = self.client.post(
            f"/api/environments/{self.team.id}/pulse_subscriptions/",
            {"enabled": True, "frequency": "weekly", "enabled_channels": ["in_app", "slack"]},
            format="json",
        )
        assert create_resp.status_code == status.HTTP_201_CREATED, create_resp.json()
        sub_id = create_resp.json()["id"]

        update_resp = self.client.patch(
            f"/api/environments/{self.team.id}/pulse_subscriptions/{sub_id}/",
            {"frequency": "daily"},
            format="json",
        )
        assert update_resp.status_code == status.HTTP_200_OK
        assert update_resp.json()["frequency"] == "daily"

    def test_subscription_rejects_unknown_channel(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/pulse_subscriptions/",
            {"enabled": True, "frequency": "weekly", "enabled_channels": ["pigeon"]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_subscription_singleton_enforced(self) -> None:
        PulseSubscription.objects.create(team=self.team)
        response = self.client.post(
            f"/api/environments/{self.team.id}/pulse_subscriptions/",
            {"enabled": True, "frequency": "weekly", "enabled_channels": ["in_app"]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
