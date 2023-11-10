from typing import Any, Dict, Optional
from unittest.mock import MagicMock, Mock, patch, ANY

import pytest
from boto3 import resource
from botocore.client import Config
from dateutil.relativedelta import relativedelta
from django.test import override_settings
from django.utils.timezone import now

from posthog.models import ExportedAsset
from posthog.models.utils import UUIDT
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.tasks.exports import csv_exporter
from posthog.tasks.exports.csv_exporter import (
    UnexpectedEmptyJsonResponse,
    add_query_params,
)
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events
from posthog.utils import absolute_uri

TEST_PREFIX = "Test-Exports"

# see GitHub issue #11204
regression_11204 = "api/projects/6642/insights/trend/?events=%5B%7B%22id%22%3A%22product%20viewed%22%2C%22name%22%3A%22product%20viewed%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&actions=%5B%5D&display=ActionsTable&insight=TRENDS&interval=day&breakdown=productName&new_entity=%5B%5D&properties=%5B%5D&step_limit=5&funnel_filter=%7B%7D&breakdown_type=event&exclude_events=%5B%5D&path_groupings=%5B%5D&include_event_types=%5B%22%24pageview%22%5D&filter_test_accounts=false&local_path_cleaning_filters=%5B%5D&date_from=-14d&offset=50"


@override_settings(SITE_URL="http://testserver")
class TestCSVExporter(APIBaseTest):
    @pytest.fixture(autouse=True)
    def patched_request(self):
        with patch("posthog.tasks.exports.csv_exporter.requests.request") as patched_request:
            mock_response = Mock()
            mock_response.status_code = 200
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

    def _create_asset(self, extra_context: Optional[Dict] = None) -> ExportedAsset:
        if extra_context is None:
            extra_context = {}

        asset = ExportedAsset(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.CSV,
            export_context={"path": "/api/literally/anything", **extra_context},
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
        bucket.objects.filter(Prefix=TEST_PREFIX).delete()

    def test_csv_exporter_writes_to_asset_when_object_storage_is_disabled(self) -> None:
        exported_asset = self._create_asset()
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            csv_exporter.export_csv(exported_asset)

            assert (
                exported_asset.content
                == b"id,distinct_id,properties.$browser,event,timestamp,person,elements_chain\r\ne9ca132e-400f-4854-a83c-16c151b2f145,2,Safari,event_name,2022-07-06T19:37:43.095295+00:00,,\r\n1624228e-a4f1-48cd-aabc-6baa3ddb22e4,2,Safari,event_name,2022-07-06T19:37:43.095279+00:00,,\r\n66d45914-bdf5-4980-a54a-7dc699bdcce9,2,Safari,event_name,2022-07-06T19:37:43.095262+00:00,,\r\n"
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
                == f"{TEST_PREFIX}/csv/team-{self.team.id}/task-{exported_asset.id}/a-guid"
            )

            content = object_storage.read(exported_asset.content_location)
            assert (
                content
                == "id,distinct_id,properties.$browser,event,timestamp,person,elements_chain\r\ne9ca132e-400f-4854-a83c-16c151b2f145,2,Safari,event_name,2022-07-06T19:37:43.095295+00:00,,\r\n1624228e-a4f1-48cd-aabc-6baa3ddb22e4,2,Safari,event_name,2022-07-06T19:37:43.095279+00:00,,\r\n66d45914-bdf5-4980-a54a-7dc699bdcce9,2,Safari,event_name,2022-07-06T19:37:43.095262+00:00,,\r\n"
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
                == b"id,distinct_id,properties.$browser,event,timestamp,person,elements_chain\r\ne9ca132e-400f-4854-a83c-16c151b2f145,2,Safari,event_name,2022-07-06T19:37:43.095295+00:00,,\r\n1624228e-a4f1-48cd-aabc-6baa3ddb22e4,2,Safari,event_name,2022-07-06T19:37:43.095279+00:00,,\r\n66d45914-bdf5-4980-a54a-7dc699bdcce9,2,Safari,event_name,2022-07-06T19:37:43.095262+00:00,,\r\n"
            )

    @patch("posthog.models.exported_asset.UUIDT")
    @patch("posthog.models.exported_asset.object_storage.write")
    def test_csv_exporter_does_not_filter_columns_on_empty_param(
        self, mocked_object_storage_write, mocked_uuidt
    ) -> None:
        exported_asset = self._create_asset({"columns": []})
        mocked_uuidt.return_value = "a-guid"
        mocked_object_storage_write.side_effect = ObjectStorageError("mock write failed")

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            csv_exporter.export_csv(exported_asset)

            assert exported_asset.content_location is None

            assert (
                exported_asset.content
                == b"id,distinct_id,properties.$browser,event,timestamp,person,elements_chain\r\ne9ca132e-400f-4854-a83c-16c151b2f145,2,Safari,event_name,2022-07-06T19:37:43.095295+00:00,,\r\n1624228e-a4f1-48cd-aabc-6baa3ddb22e4,2,Safari,event_name,2022-07-06T19:37:43.095279+00:00,,\r\n66d45914-bdf5-4980-a54a-7dc699bdcce9,2,Safari,event_name,2022-07-06T19:37:43.095262+00:00,,\r\n"
            )

    @patch("posthog.models.exported_asset.UUIDT")
    @patch("posthog.models.exported_asset.object_storage.write")
    def test_csv_exporter_does_filter_columns(self, mocked_object_storage_write, mocked_uuidt) -> None:
        # NB these columns are not in the "natural" order
        exported_asset = self._create_asset({"columns": ["distinct_id", "properties.$browser", "event"]})
        mocked_uuidt.return_value = "a-guid"
        mocked_object_storage_write.side_effect = ObjectStorageError("mock write failed")

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            csv_exporter.export_csv(exported_asset)

            assert exported_asset.content_location is None

            assert (
                exported_asset.content
                == b"distinct_id,properties.$browser,event\r\n2,Safari,event_name\r\n2,Safari,event_name\r\n2,Safari,event_name\r\n"
            )

    @patch("posthog.models.exported_asset.UUIDT")
    @patch("posthog.models.exported_asset.object_storage.write")
    def test_csv_exporter_does_filter_columns_and_can_handle_unexpected_columns(
        self, mocked_object_storage_write, mocked_uuidt
    ) -> None:
        # NB these columns are not in the "natural" order
        exported_asset = self._create_asset({"columns": ["distinct_id", "properties.$browser", "event", "tomato"]})
        mocked_uuidt.return_value = "a-guid"
        mocked_object_storage_write.side_effect = ObjectStorageError("mock write failed")

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            csv_exporter.export_csv(exported_asset)

            assert exported_asset.content_location is None

            assert (
                exported_asset.content
                == b"distinct_id,properties.$browser,event,tomato\r\n2,Safari,event_name,\r\n2,Safari,event_name,\r\n2,Safari,event_name,\r\n"
            )

    @patch("posthog.models.exported_asset.UUIDT")
    @patch("posthog.models.exported_asset.object_storage.write")
    @patch("requests.request")
    def test_csv_exporter_limits_breakdown_insights_correctly(
        self, mocked_request, mocked_object_storage_write, mocked_uuidt
    ) -> None:
        path = "api/projects/1/insights/trend/?insight=TRENDS&breakdown=email&date_from=-7d"
        exported_asset = self._create_asset({"path": path})
        mock_response = Mock()
        mock_response.status_code = 200
        mocked_request.return_value = mock_response

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            csv_exporter.export_csv(exported_asset)

        mocked_request.assert_called_with(
            method="get",
            url="http://testserver/" + path + "&breakdown_limit=1000&is_csv_export=1",
            json=None,
            headers=ANY,
        )

    @patch("posthog.tasks.exports.csv_exporter.logger")
    def test_failing_export_api_is_reported(self, _mock_logger: MagicMock) -> None:
        with patch("posthog.tasks.exports.csv_exporter.requests.request") as patched_request:
            exported_asset = self._create_asset()
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.ok = False
            patched_request.return_value = mock_response

            with pytest.raises(Exception, match="export API call failed with status_code: 403"):
                csv_exporter.export_csv(exported_asset)

    def test_limiting_query_as_expected(self) -> None:
        with self.settings(SITE_URL="https://app.posthog.com"):
            modified_url = add_query_params(absolute_uri(regression_11204), {"limit": "3500"})
            actual_bits = self._split_to_dict(modified_url)
            expected_bits = {
                **self._split_to_dict(regression_11204),
                **{"limit": "3500"},
            }
            assert expected_bits == actual_bits

    def test_limiting_existing_limit_query_as_expected(self) -> None:
        with self.settings(SITE_URL="https://app.posthog.com"):
            url_with_existing_limit = regression_11204 + "&limit=100000"
            modified_url = add_query_params(absolute_uri(url_with_existing_limit), {"limit": "3500"})
            actual_bits = self._split_to_dict(modified_url)
            expected_bits = {
                **self._split_to_dict(regression_11204),
                **{"limit": "3500"},
            }
            assert expected_bits == actual_bits

    @patch("posthog.tasks.exports.csv_exporter.make_api_call")
    def test_raises_expected_error_when_json_is_none(self, patched_api_call) -> None:
        mock_response = Mock()
        mock_response.json.return_value = None
        mock_response.status_code = 200
        mock_response.text = "i am the text"
        patched_api_call.return_value = mock_response

        with pytest.raises(UnexpectedEmptyJsonResponse, match="JSON is None when calling API for data"):
            csv_exporter.export_csv(self._create_asset())

    @patch("posthog.hogql.constants.MAX_SELECT_RETURNED_ROWS", 10)
    @patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 5)
    @patch("posthog.models.exported_asset.UUIDT")
    def test_csv_exporter_hogql_query(self, mocked_uuidt, DEFAULT_RETURNED_ROWS=5, MAX_SELECT_RETURNED_ROWS=10) -> None:
        random_uuid = str(UUIDT())
        for i in range(15):
            _create_event(
                event="$pageview",
                distinct_id=random_uuid,
                team=self.team,
                timestamp=now() - relativedelta(hours=1),
                properties={"prop": i},
            )
        flush_persons_and_events()

        exported_asset = ExportedAsset(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.CSV,
            export_context={
                "source": {
                    "kind": "HogQLQuery",
                    "query": f"select event from events where distinct_id = '{random_uuid}'",
                }
            },
        )
        exported_asset.save()
        mocked_uuidt.return_value = "a-guid"

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            csv_exporter.export_csv(exported_asset)

            assert (
                exported_asset.content_location
                == f"{TEST_PREFIX}/csv/team-{self.team.id}/task-{exported_asset.id}/a-guid"
            )

            content = object_storage.read(exported_asset.content_location)
            assert (
                content
                == "event\r\n$pageview\r\n$pageview\r\n$pageview\r\n$pageview\r\n$pageview\r\n$pageview\r\n$pageview\r\n$pageview\r\n$pageview\r\n$pageview\r\n"
            )

            assert exported_asset.content is None

    @patch("posthog.hogql.constants.MAX_SELECT_RETURNED_ROWS", 10)
    @patch("posthog.models.exported_asset.UUIDT")
    def test_csv_exporter_events_query(self, mocked_uuidt, MAX_SELECT_RETURNED_ROWS=10) -> None:
        random_uuid = str(UUIDT())
        for i in range(15):
            _create_event(
                event="$pageview",
                distinct_id=random_uuid,
                team=self.team,
                timestamp=now() - relativedelta(hours=1),
                properties={"prop": i},
            )
        flush_persons_and_events()

        exported_asset = ExportedAsset(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.CSV,
            export_context={
                "source": {
                    "kind": "EventsQuery",
                    "select": ["event", "*"],
                    "where": [f"distinct_id = '{random_uuid}'"],
                }
            },
        )
        exported_asset.save()
        mocked_uuidt.return_value = "a-guid"

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            csv_exporter.export_csv(exported_asset)
            content = object_storage.read(exported_asset.content_location)
            lines = (content or "").split("\r\n")
            self.assertEqual(len(lines), 12)
            self.assertEqual(
                lines[0],
                "event,*.uuid,*.event,*.properties.prop,*.timestamp,*.team_id,*.distinct_id,*.elements_chain,*.created_at",
            )
            self.assertEqual(lines[11], "")
            first_row = lines[1].split(",")
            self.assertEqual(first_row[0], "$pageview")
            self.assertEqual(first_row[2], "$pageview")
            self.assertEqual(first_row[5], str(self.team.pk))

    def _split_to_dict(self, url: str) -> Dict[str, Any]:
        first_split_parts = url.split("?")
        assert len(first_split_parts) == 2
        return {bits[0]: bits[1] for bits in [param.split("=") for param in first_split_parts[1].split("&")]}
