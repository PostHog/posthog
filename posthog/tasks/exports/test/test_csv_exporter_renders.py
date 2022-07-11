import json
import os
from unittest.mock import Mock, patch

from posthog.models import ExportedAsset
from posthog.tasks.exports import csv_exporter
from posthog.test.base import APIBaseTest

TEST_BUCKET = "Test-Exports"

directory = os.path.join(os.path.abspath(os.path.dirname(__file__)), "./csv_renders")
fixtures = []

for file in os.listdir(directory):
    filename = os.fsdecode(file)
    if filename.endswith(".json"):
        fixtures.append(filename)


class TestCSVExporterRenders(APIBaseTest):
    @patch("posthog.tasks.exports.csv_exporter.requests.request")
    def test_response_renders(self, mock_request) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            for filename in fixtures:
                # print(os.path.join(directory, filename))
                with open(os.path.join(directory, filename)) as f:
                    fixture = json.loads(f.read())

                print(f"Testing csv case: {filename}")  # noqa

                asset = ExportedAsset(
                    team=self.team,
                    export_format=ExportedAsset.ExportFormat.CSV,
                    export_context={"path": "/api/literally/anything"},
                )
                asset.save()

                mock = Mock()
                mock.json.return_value = fixture["response"]
                mock_request.return_value = mock
                csv_exporter.export_csv(asset)
                csv_rows = asset.content.decode("utf-8").split("\r\n")

                print("Got csv data:")  # noqa
                print({"csv_rows": csv_rows})  # noqa

                assert csv_rows == fixture["csv_rows"]
