from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from prometheus_client import REGISTRY

from posthog.egress.workos_radar import workos_radar_report

_API_KEY = "sk_test_radar_key"
_ATTEMPT_ID = "radar_att_01TRANSPORT"


def _request_count(status_code: str) -> float:
    labels = {
        "api_key": "default",
        "method": "PUT",
        "endpoint": "attempts/:id",
        "status_code": status_code,
        "source": "success_report",
    }
    return REGISTRY.get_sample_value("workos_radar_api_requests_total", labels) or 0


def _label_values() -> list[str]:
    return [
        value
        for metric in REGISTRY.collect()
        if metric.name.startswith("workos_radar_api")
        for sample in metric.samples
        for value in sample.labels.values()
    ]


class TestWorkosRadarTransport(SimpleTestCase):
    def test_request_carries_the_key_and_is_recorded_without_the_key_or_the_attempt_id(self) -> None:
        response = requests.Response()
        response.status_code = 200
        before = _request_count("200")

        with patch("requests.request", return_value=response) as request:
            workos_radar_report(
                f"https://api.workos.com/radar/attempts/{_ATTEMPT_ID}",
                api_key=_API_KEY,
                timeout=1.0,
                json={"attempt_status": "success"},
            )

        assert request.call_args.kwargs["headers"]["Authorization"] == f"Bearer {_API_KEY}"
        assert _request_count("200") == before + 1
        assert not any(_API_KEY in value or _ATTEMPT_ID in value for value in _label_values())
