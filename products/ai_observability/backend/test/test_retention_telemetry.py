from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from posthoganalytics import Posthog

from posthog.ph_client import PH_US_API_KEY, PH_US_HOST, get_client

from products.ai_observability.backend.tasks import dataset_retention, offline_payload_retention


class TestRetentionTelemetry(SimpleTestCase):
    @parameterized.expand([(job, region) for job in ("datasets", "offline_payloads") for region in ("US", "EU", None)])
    def test_cleanup_events_reach_us_with_the_origin_region(self, job: str, region: str | None) -> None:
        module, sweep, task = (
            (dataset_retention, "DatasetRetention", dataset_retention.expire_datasets)
            if job == "datasets"
            else (
                offline_payload_retention,
                "OfflinePayloadRetention",
                offline_payload_retention.expire_offline_evaluation_payloads,
            )
        )
        before_send = MagicMock(side_effect=lambda event: event)
        clients: list[Posthog] = []

        def make_client(destination: str) -> Posthog:
            client = get_client(
                destination, send=False, disabled=False, enable_local_evaluation=False, before_send=before_send
            )
            clients.append(client)
            return client

        with (
            override_settings(CLOUD_DEPLOYMENT=region or "US"),
            patch(f"{module.__name__}.{sweep}.run"),
            patch(f"{module.__name__}.get_instance_region", return_value=region),
            patch("posthog.ph_client.get_client", side_effect=make_client),
        ):
            task()

        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].host, PH_US_HOST)
        self.assertEqual(clients[0].api_key, PH_US_API_KEY)
        event = before_send.call_args.args[0]
        self.assertEqual(event["properties"]["region"], region or "US")
        self.assertEqual(event["properties"]["status"], "completed")
        self.assertEqual(event["properties"]["payload_bytes_deleted"], 0)
