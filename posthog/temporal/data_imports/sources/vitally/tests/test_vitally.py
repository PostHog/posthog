from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

from posthog.temporal.data_imports.sources.vitally.settings import CUSTOM_OBJECT_SCHEMA_PREFIX
from posthog.temporal.data_imports.sources.vitally.source import VitallySource
from posthog.temporal.data_imports.sources.vitally.vitally import (
    get_custom_object_records_resource,
    list_custom_object_definitions,
    vitally_source,
)


def _make_response(json_data: dict[str, Any], status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    response.raise_for_status = Mock()
    return response


def _make_session(responses: list[Mock]) -> MagicMock:
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.send.side_effect = responses
    # prepare_request returns its argument unchanged so the paginator's url updates
    # propagate to the next send() call.
    session.prepare_request.side_effect = lambda r: r
    return session


FEATURE_REQUEST_DEFINITION = {
    "id": "f5dcbbd6-c69d-4402-b00e-7a34a27aded5",
    "name": "featureRequest",
    "label": "Feature Request",
}
OPPORTUNITY_DEFINITION = {
    "id": "5b50ffc0-849e-47e4-9954-25071a7d3636",
    "name": "Opportunity",
    "label": "Opportunity",
}


class TestListCustomObjectDefinitions:
    @patch("posthog.temporal.data_imports.sources.vitally.vitally.make_tracked_session")
    def test_returns_results_from_single_page(self, mock_session_factory):
        session = _make_session([_make_response({"results": [FEATURE_REQUEST_DEFINITION], "next": None})])
        mock_session_factory.return_value = session

        defs = list_custom_object_definitions("secret", "EU", None)

        assert defs == [FEATURE_REQUEST_DEFINITION]
        assert session.send.call_count == 1

    @patch("posthog.temporal.data_imports.sources.vitally.vitally.make_tracked_session")
    def test_paginates_until_next_is_null(self, mock_session_factory):
        session = _make_session(
            [
                _make_response({"results": [FEATURE_REQUEST_DEFINITION], "next": "cursor-2"}),
                _make_response({"results": [OPPORTUNITY_DEFINITION], "next": None}),
            ]
        )
        mock_session_factory.return_value = session

        defs = list_custom_object_definitions("secret", "EU", None)

        assert defs == [FEATURE_REQUEST_DEFINITION, OPPORTUNITY_DEFINITION]
        assert session.send.call_count == 2

    @patch("posthog.temporal.data_imports.sources.vitally.vitally.make_tracked_session")
    def test_empty_results_returns_empty_list(self, mock_session_factory):
        session = _make_session([_make_response({"results": [], "next": None})])
        mock_session_factory.return_value = session

        assert list_custom_object_definitions("secret", "EU", None) == []

    @patch("posthog.temporal.data_imports.sources.vitally.vitally.make_tracked_session")
    def test_raises_on_http_error(self, mock_session_factory):
        bad = _make_response({}, status_code=401)
        bad.raise_for_status.side_effect = RuntimeError("401 Unauthorized")
        mock_session_factory.return_value = _make_session([bad])

        with pytest.raises(RuntimeError, match="401 Unauthorized"):
            list_custom_object_definitions("secret", "EU", None)


class TestGetCustomObjectRecordsResource:
    def test_path_uses_custom_object_id(self):
        resource = get_custom_object_records_resource("featureRequest", "f5dcbbd6", should_use_incremental_field=False)

        assert resource["endpoint"]["path"] == "/resources/customObjects/f5dcbbd6/instances"
        assert resource["name"] == f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"
        assert resource["table_name"] == "custom_object_featurerequest"
        assert resource["write_disposition"] == "replace"

    def test_incremental_field_enables_upsert_and_cursor(self):
        resource = get_custom_object_records_resource("featureRequest", "abc", should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        params = cast(dict[str, Any], resource["endpoint"]["params"])
        assert params["sortBy"] == "updatedAt"
        updated_at_config = params["updatedAt"]
        assert isinstance(updated_at_config, dict)
        assert updated_at_config["type"] == "incremental"
        assert updated_at_config["cursor_path"] == "updatedAt"


class TestVitallySourceCustomObjectRouting:
    @patch("posthog.temporal.data_imports.sources.vitally.vitally.rest_api_resource")
    @patch("posthog.temporal.data_imports.sources.vitally.vitally.list_custom_object_definitions")
    def test_resolves_machine_name_to_custom_object_id(self, mock_list, mock_rest_api):
        mock_list.return_value = [FEATURE_REQUEST_DEFINITION, OPPORTUNITY_DEFINITION]
        mock_rest_api.return_value = iter([{"id": "rec-1"}, {"id": "rec-2"}])

        rows = list(
            vitally_source(
                secret_token="secret",
                region="EU",
                subdomain=None,
                endpoint=f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest",
                team_id=1,
                job_id="job-1",
                logger=MagicMock(),
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
            )
        )

        assert rows == [{"id": "rec-1"}, {"id": "rec-2"}]
        rest_call_kwargs = mock_rest_api.call_args
        config = rest_call_kwargs.args[0]
        assert len(config["resources"]) == 1
        assert (
            config["resources"][0]["endpoint"]["path"]
            == "/resources/customObjects/f5dcbbd6-c69d-4402-b00e-7a34a27aded5/instances"
        )

    @patch("posthog.temporal.data_imports.sources.vitally.vitally.list_custom_object_definitions")
    def test_raises_for_unknown_custom_object(self, mock_list):
        mock_list.return_value = [OPPORTUNITY_DEFINITION]

        with pytest.raises(ValueError, match="featureRequest"):
            list(
                vitally_source(
                    secret_token="secret",
                    region="EU",
                    subdomain=None,
                    endpoint=f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest",
                    team_id=1,
                    job_id="job-1",
                    logger=MagicMock(),
                    db_incremental_field_last_value=None,
                    should_use_incremental_field=False,
                )
            )


class TestVitallySourceGetSchemas:
    def _make_config(self):
        config = MagicMock()
        config.secret_token = "secret"
        config.region.selection = "EU"
        config.region.subdomain = None
        return config

    @patch("posthog.temporal.data_imports.sources.vitally.source.list_custom_object_definitions")
    def test_includes_static_endpoints_and_dynamic_custom_objects(self, mock_list):
        mock_list.return_value = [FEATURE_REQUEST_DEFINITION, OPPORTUNITY_DEFINITION]

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        names = {s.name for s in schemas}
        # Static endpoints
        assert {"Accounts", "Conversations", "Custom_Objects", "Messages"} <= names
        # Dynamic custom object schemas
        assert f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest" in names
        assert f"{CUSTOM_OBJECT_SCHEMA_PREFIX}Opportunity" in names

        feature_request = next(s for s in schemas if s.name == f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest")
        assert feature_request.label == "Feature Request"
        assert feature_request.supports_incremental is True
        assert feature_request.supports_append is True
        assert len(feature_request.incremental_fields) == 1

    @patch("posthog.temporal.data_imports.sources.vitally.source.list_custom_object_definitions")
    def test_skips_definitions_without_a_name(self, mock_list):
        mock_list.return_value = [{"id": "abc", "name": "", "label": "empty"}, FEATURE_REQUEST_DEFINITION]

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        dynamic = [s for s in schemas if s.name.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX)]
        assert len(dynamic) == 1
        assert dynamic[0].name == f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"

    @patch("posthog.temporal.data_imports.sources.vitally.source.list_custom_object_definitions")
    def test_falls_back_to_machine_name_when_label_missing(self, mock_list):
        mock_list.return_value = [{"id": "abc", "name": "widget"}]

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        widget = next(s for s in schemas if s.name == f"{CUSTOM_OBJECT_SCHEMA_PREFIX}widget")
        assert widget.label == "widget"

    @patch("posthog.temporal.data_imports.sources.vitally.source.list_custom_object_definitions")
    def test_names_filter_applies_to_both_static_and_dynamic(self, mock_list):
        mock_list.return_value = [FEATURE_REQUEST_DEFINITION]

        schemas = VitallySource().get_schemas(
            self._make_config(),
            team_id=1,
            names=["Accounts", f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"],
        )

        assert {s.name for s in schemas} == {"Accounts", f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"}
