import os
import json

import pytest
from unittest.mock import Mock, patch

from posthog.models import ExportedAsset
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.tasks.exports import csv_exporter

TEST_BUCKET = "Test-Exports"

directory = os.path.join(os.path.abspath(os.path.dirname(__file__)), "./csv_renders")
fixtures = []

for file in os.listdir(directory):
    filename = os.fsdecode(file)
    if filename.endswith(".json"):
        fixtures.append(filename)


@pytest.mark.parametrize("filename", fixtures)
@pytest.mark.parametrize("mode", ("legacy", "hogql"))
@pytest.mark.django_db
@patch("posthog.tasks.exports.csv_exporter.requests.request")
@patch("posthog.tasks.exports.csv_exporter.process_query_dict")
@patch("posthog.models.exported_asset.settings")
def test_csv_rendering(mock_settings, mock_process_query_dict, mock_request, filename, mode):
    mock_settings.OBJECT_STORAGE_ENABLED = False
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org, name="team")

    with open(os.path.join(directory, filename), encoding="utf_8") as f:
        fixture = json.load(f)

    asset = ExportedAsset(
        team=team,
        export_format=ExportedAsset.ExportFormat.CSV,
        export_context={"path": "/api/literally/anything"},
    )
    if fixture["response"].get("columns"):
        asset.export_context["columns"] = fixture["response"]["columns"]
    asset.save()

    if mode == "legacy":
        mock = Mock()
        mock.status_code = 200
        mock.json.return_value = fixture["response"]
        mock_request.return_value = mock
        csv_exporter.export_tabular(asset)
        csv_rows = asset.content.decode("utf-8").split("\r\n")

        assert csv_rows == fixture["csv_rows"]

    if mode == "hogql":
        asset.export_context["source"] = {"some": "query"}
        asset.save()
        if fixture.get("hogql_response"):
            # If HogQL has a different response structure, add it to the fixture as `hogql_response`
            mock_process_query_dict.return_value = fixture["hogql_response"]
        elif fixture["response"].get("results") is not None:
            mock_process_query_dict.return_value = fixture["response"]
        else:
            mock_process_query_dict.return_value = fixture["response"]
            if "result" in fixture["response"]:
                mock_process_query_dict.return_value["results"] = fixture["response"].pop("result")
        csv_exporter.export_tabular(asset)
        csv_rows = asset.content.decode("utf-8").split("\r\n")

        assert csv_rows == fixture["csv_rows"]
