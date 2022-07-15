from unittest.mock import Mock, patch

import pytest
from boto3 import resource
from botocore.client import Config

from posthog.models import ExportedAsset
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.tasks.exports import csv_exporter
from posthog.test.base import APIBaseTest

TEST_BUCKET = "Test-Exports"


class TestCSVExporter(APIBaseTest):
    @pytest.fixture(autouse=True)
    def patched_request(self):
        with patch("posthog.tasks.exports.csv_exporter.requests.request") as patched_request:
            mock_response = Mock()
            # API responses copied from https://github.com/PostHog/posthog/runs/7221634689?check_suite_focus=true
            mock_response.json.side_effect = [
                {
                    "next": "http://testserver/api/projects/169/events?orderBy=%5B%22-timestamp%22%5D&properties=%5B%7B%22key%22%3A%22%24browser%22%2C%22value%22%3A%5B%22Safari%22%5D%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22event%22%7D%5D&after=2022-07-06T19%3A27%3A43.206326&limit=1&before=2022-07-06T19%3A37%3A43.095295%2B00%3A00",
                    "results": [
                        {
                            "id": "e9ca132e-400f-4854-a83c-16c151b2f145",
                            "distinct_id": "2",
                            "properties": {"$browser": "Safari"},
                            "event": "event_name",
                            "timestamp": "2022-07-06T19:37:43.095295+00:00",
                            "person": None,
                            "elements": [],
                            "elements_chain": "",
                        }
                    ],
                },
                {
                    "next": "http://testserver/api/projects/169/events?orderBy=%5B%22-timestamp%22%5D&properties=%5B%7B%22key%22%3A%22%24browser%22%2C%22value%22%3A%5B%22Safari%22%5D%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22event%22%7D%5D&after=2022-07-06T19%3A27%3A43.206326&limit=1&before=2022-07-06T19%3A37%3A43.095279%2B00%3A00",
                    "results": [
                        {
                            "id": "1624228e-a4f1-48cd-aabc-6baa3ddb22e4",
                            "distinct_id": "2",
                            "properties": {"$browser": "Safari"},
                            "event": "event_name",
                            "timestamp": "2022-07-06T19:37:43.095279+00:00",
                            "person": None,
                            "elements": [],
                            "elements_chain": "",
                        }
                    ],
                },
                {
                    "next": None,
                    "results": [
                        {
                            "id": "66d45914-bdf5-4980-a54a-7dc699bdcce9",
                            "distinct_id": "2",
                            "properties": {"$browser": "Safari"},
                            "event": "event_name",
                            "timestamp": "2022-07-06T19:37:43.095262+00:00",
                            "person": None,
                            "elements": [],
                            "elements_chain": "",
                        }
                    ],
                },
            ]
            patched_request.return_value = mock_response
            yield patched_request

    def _create_asset(self) -> ExportedAsset:
        asset = ExportedAsset(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.CSV,
            export_context={"path": "/api/literally/anything"},
        )
        asset.save()
        return asset

    def teardown_method(self, method):
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

    def test_csv_exporter_writes_to_asset_when_object_storage_is_disabled(self) -> None:
        exported_asset = self._create_asset()
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            csv_exporter.export_csv(exported_asset)

            assert (
                exported_asset.content
                == b"distinct_id,elements_chain,event,id,person,properties.$browser,timestamp\r\n2,,event_name,e9ca132e-400f-4854-a83c-16c151b2f145,,Safari,2022-07-06T19:37:43.095295+00:00\r\n2,,event_name,1624228e-a4f1-48cd-aabc-6baa3ddb22e4,,Safari,2022-07-06T19:37:43.095279+00:00\r\n2,,event_name,66d45914-bdf5-4980-a54a-7dc699bdcce9,,Safari,2022-07-06T19:37:43.095262+00:00\r\n"
            )
            assert exported_asset.content_location is None

    @patch("posthog.models.exported_asset.UUIDT")
    def test_csv_exporter_writes_to_object_storage_when_object_storage_is_enabled(self, mocked_uuidt) -> None:
        exported_asset = self._create_asset()
        mocked_uuidt.return_value = "a-guid"

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            csv_exporter.export_csv(exported_asset)

            assert (
                exported_asset.content_location
                == f"/{TEST_BUCKET}/csv/team-{self.team.id}/task-{exported_asset.id}/a-guid"
            )

            content = object_storage.read(exported_asset.content_location)
            assert (
                content
                == "distinct_id,elements_chain,event,id,person,properties.$browser,timestamp\r\n2,,event_name,e9ca132e-400f-4854-a83c-16c151b2f145,,Safari,2022-07-06T19:37:43.095295+00:00\r\n2,,event_name,1624228e-a4f1-48cd-aabc-6baa3ddb22e4,,Safari,2022-07-06T19:37:43.095279+00:00\r\n2,,event_name,66d45914-bdf5-4980-a54a-7dc699bdcce9,,Safari,2022-07-06T19:37:43.095262+00:00\r\n"
            )

            assert exported_asset.content is None

    @patch("posthog.models.exported_asset.UUIDT")
    @patch("posthog.models.exported_asset.object_storage.write")
    def test_csv_exporter_writes_to_asset_when_object_storage_write_fails(
        self, mocked_object_storage_write, mocked_uuidt
    ) -> None:
        exported_asset = self._create_asset()
        mocked_uuidt.return_value = "a-guid"
        mocked_object_storage_write.side_effect = ObjectStorageError("mock write failed")

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            csv_exporter.export_csv(exported_asset)

            assert exported_asset.content_location is None

            assert (
                exported_asset.content
                == b"distinct_id,elements_chain,event,id,person,properties.$browser,timestamp\r\n2,,event_name,e9ca132e-400f-4854-a83c-16c151b2f145,,Safari,2022-07-06T19:37:43.095295+00:00\r\n2,,event_name,1624228e-a4f1-48cd-aabc-6baa3ddb22e4,,Safari,2022-07-06T19:37:43.095279+00:00\r\n2,,event_name,66d45914-bdf5-4980-a54a-7dc699bdcce9,,Safari,2022-07-06T19:37:43.095262+00:00\r\n"
            )
