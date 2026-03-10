from datetime import timedelta

from freezegun.api import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status

from posthog.api.spike_alerts import _SPIKE_EVENT, _SPIKE_LOG_TYPE, _spike_date
from posthog.models.organization import Organization


def _spike_event_properties(organization_id: str, detected_spikes: list[dict]) -> dict:
    return {
        "log_type": _SPIKE_LOG_TYPE,
        "organization_id": organization_id,
        "detected_spikes": detected_spikes,
    }


def _make_spike(usage_key: str, z_score: float, date: str = "2026-02-28") -> dict:
    # value and weekday_average are pre-formatted strings in real events (e.g. "77,345")
    return {
        "usage_key": usage_key,
        "value": "100",
        "weekday_average": "50",
        "z_score": z_score,
        "date": date,
    }


class TestSpikeDate(APIBaseTest):
    @parameterized.expand(
        [
            ("returns_date_from_first_spike", [{"date": "2026-02-28"}], "fallback", "2026-02-28"),
            ("ignores_subsequent_spikes", [{"date": "2026-02-28"}, {"date": "2026-02-01"}], "fallback", "2026-02-28"),
            ("falls_back_when_empty_spikes", [], "fallback-date", "fallback-date"),
            ("falls_back_when_spike_has_no_date", [{"z_score": 5.0}], "fallback-date", "fallback-date"),
        ]
    )
    def test_spike_date(self, _name, detected_spikes, fallback, expected_date):
        assert _spike_date(detected_spikes, fallback) == expected_date


class TestSpikeAlertsAPI(ClickhouseTestMixin, APIBaseTest):
    def _url(self) -> str:
        return f"/api/environments/{self.team.pk}/spike_alerts/"

    @freeze_time("2026-03-02T12:00:00Z")
    def test_returns_spike_alerts_for_org(self):
        org_id = str(self.team.organization_id)
        spikes_a = [_make_spike("events", z_score=4.5, date="2026-02-28")]
        spikes_b = [_make_spike("recordings", z_score=6.2, date="2026-02-27")]

        _create_event(
            team=self.team,
            event=_SPIKE_EVENT,
            distinct_id="billing-system",
            timestamp=now() - timedelta(days=1),
            properties=_spike_event_properties(org_id, spikes_a),
        )
        _create_event(
            team=self.team,
            event=_SPIKE_EVENT,
            distinct_id="billing-system",
            timestamp=now() - timedelta(days=2),
            properties=_spike_event_properties(org_id, spikes_b),
        )
        flush_persons_and_events()

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 2
        assert len(data["results"]) == 2

        first = data["results"][0]
        assert "id" in first
        assert first["detected_spikes"] == spikes_a
        assert first["spike_date"] == "2026-02-28"
        assert "detected_at" in first

        second = data["results"][1]
        assert second["detected_spikes"] == spikes_b

    @freeze_time("2026-03-02T12:00:00Z")
    def test_isolates_by_organization(self):
        org_id = str(self.team.organization_id)
        other_org = Organization.objects.bootstrap(None)[0]
        other_org_id = str(other_org.id)

        spikes_own = [_make_spike("events", z_score=4.5)]
        spikes_other = [_make_spike("recordings", z_score=5.0)]

        _create_event(
            team=self.team,
            event=_SPIKE_EVENT,
            distinct_id="billing-system",
            timestamp=now() - timedelta(days=1),
            properties=_spike_event_properties(org_id, spikes_own),
        )
        _create_event(
            team=self.team,
            event=_SPIKE_EVENT,
            distinct_id="billing-system",
            timestamp=now() - timedelta(days=1),
            properties=_spike_event_properties(other_org_id, spikes_other),
        )
        flush_persons_and_events()

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["detected_spikes"] == spikes_own

    @freeze_time("2026-03-02T12:00:00Z")
    def test_excludes_events_older_than_30_days(self):
        org_id = str(self.team.organization_id)
        spikes_recent = [_make_spike("events", z_score=4.5)]
        spikes_old = [_make_spike("recordings", z_score=5.0)]

        _create_event(
            team=self.team,
            event=_SPIKE_EVENT,
            distinct_id="billing-system",
            timestamp=now() - timedelta(days=1),
            properties=_spike_event_properties(org_id, spikes_recent),
        )
        _create_event(
            team=self.team,
            event=_SPIKE_EVENT,
            distinct_id="billing-system",
            timestamp=now() - timedelta(days=31),
            properties=_spike_event_properties(org_id, spikes_old),
        )
        flush_persons_and_events()

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["detected_spikes"] == spikes_recent

    @freeze_time("2026-03-02T12:00:00Z")
    def test_pagination(self):
        org_id = str(self.team.organization_id)

        for i in range(3):
            _create_event(
                team=self.team,
                event=_SPIKE_EVENT,
                distinct_id="billing-system",
                timestamp=now() - timedelta(hours=i + 1),
                properties=_spike_event_properties(org_id, [_make_spike(f"metric_{i}", z_score=4.5)]),
            )
        flush_persons_and_events()

        first_page = self.client.get(self._url(), {"limit": 2, "offset": 0})
        assert first_page.status_code == status.HTTP_200_OK
        first_data = first_page.json()
        assert first_data["count"] == 3
        assert len(first_data["results"]) == 2

        second_page = self.client.get(self._url(), {"limit": 2, "offset": 2})
        assert second_page.status_code == status.HTTP_200_OK
        second_data = second_page.json()
        assert second_data["count"] == 3
        assert len(second_data["results"]) == 1

    @freeze_time("2026-03-02T12:00:00Z")
    def test_spike_date_comes_from_detected_spikes(self):
        org_id = str(self.team.organization_id)
        spikes = [_make_spike("events", z_score=4.5, date="2026-02-25")]

        _create_event(
            team=self.team,
            event=_SPIKE_EVENT,
            distinct_id="billing-system",
            timestamp=now() - timedelta(days=1),
            properties=_spike_event_properties(org_id, spikes),
        )
        flush_persons_and_events()

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["spike_date"] == "2026-02-25"
