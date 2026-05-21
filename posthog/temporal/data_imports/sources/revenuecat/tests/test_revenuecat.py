from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from posthog.temporal.data_imports.sources.revenuecat import revenuecat as api_client
from posthog.temporal.data_imports.sources.revenuecat.constants import (
    REVENUECAT_API_BASE_URL,
    REVENUECAT_AUTO_WEBHOOK_NAME,
    REVENUECAT_WEBHOOK_EVENT_TYPES,
)


def _ok_json_response(payload: dict | list | None = None, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.raise_for_status = MagicMock()
    return response


def _http_error_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


class TestValidateCredentials:
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_true_when_projects_list_succeeds(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"items": []})

        success, error = api_client.validate_credentials("sk_test", project_id=None)

        assert success is True
        assert error is None
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{REVENUECAT_API_BASE_URL}/projects"

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_also_checks_project_when_id_provided(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _ok_json_response({"items": []}),
            _ok_json_response({"id": "proj_test"}),
        ]

        success, _ = api_client.validate_credentials("sk_test", project_id="proj_test")

        assert success is True
        # Second call hits the project-specific endpoint.
        second_call_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert second_call_url == f"{REVENUECAT_API_BASE_URL}/projects/proj_test"

    @parameterized.expand(
        [
            (401, "rejected the API key"),
            (403, "denied"),
            (404, "could not find"),
            (429, "rate-limited"),
            (500, "RevenueCat API error"),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_false_on_http_error(self, status_code, expected_substring, mock_session):
        mock_session.return_value.get.return_value = _http_error_response(status_code)

        success, error = api_client.validate_credentials("sk_test", project_id=None)

        assert success is False
        assert error is not None
        assert expected_substring.lower() in error.lower()

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_false_on_network_error(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("dns fail")

        success, error = api_client.validate_credentials("sk_test", project_id=None)

        assert success is False
        assert error is not None
        assert "Could not reach RevenueCat" in error

    @parameterized.expand(
        [
            (401, "rejected the API key"),
            (403, "denied"),
            (404, "could not find"),
            (429, "rate-limited"),
            (500, "RevenueCat API error"),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_false_when_project_specific_call_fails(self, status_code, expected_substring, mock_session):
        # The first call (`GET /projects`) succeeds, but the per-project follow-up
        # (`GET /projects/{id}`) fails. `_format_http_error` is shared between
        # both call sites, so without this branch a regression in the per-project
        # path would go unnoticed.
        mock_session.return_value.get.side_effect = [
            _ok_json_response({"items": []}),
            _http_error_response(status_code),
        ]

        success, error = api_client.validate_credentials("sk_test", project_id="proj_test")

        assert success is False
        assert error is not None
        assert expected_substring.lower() in error.lower()


class TestIterateListEndpoint:
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_follows_next_page_until_exhausted(self, mock_session):
        # Two pages: first returns one row + a relative next_page, second
        # returns one row with no next_page. The iterator should yield both
        # rows in order and stop without making a third call.
        first = _ok_json_response(
            {
                "items": [{"id": "cus_1", "name": "first"}],
                "next_page": "/v2/projects/proj_test/customers?starting_after=cus_1&limit=100",
            }
        )
        second = _ok_json_response({"items": [{"id": "cus_2", "name": "second"}], "next_page": None})
        mock_session.return_value.get.side_effect = [first, second]

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test",
                project_id="proj_test",
                path_suffix="/customers",
                endpoint_name="customers",
            )
        )

        assert rows == [{"id": "cus_1", "name": "first"}, {"id": "cus_2", "name": "second"}]
        assert mock_session.return_value.get.call_count == 2

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_invokes_on_cursor_advance_with_last_row_id_per_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _ok_json_response(
                {
                    "items": [{"id": "cus_1"}, {"id": "cus_2"}],
                    "next_page": "/v2/projects/proj_test/customers?starting_after=cus_2",
                }
            ),
            _ok_json_response({"items": [{"id": "cus_3"}], "next_page": None}),
        ]
        seen: list[tuple[str, str]] = []

        list(
            api_client.iterate_list_endpoint(
                "sk_test",
                project_id="proj_test",
                path_suffix="/customers",
                endpoint_name="customers",
                on_cursor_advance=lambda name, last_id: seen.append((name, last_id)),
            )
        )

        # Saved after each page's last row — never before, otherwise a crash
        # would skip the page rather than re-yield it (merge dedupes on PK).
        assert seen == [("customers", "cus_2"), ("customers", "cus_3")]

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_uses_starting_after_when_resuming(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"items": [], "next_page": None})

        list(
            api_client.iterate_list_endpoint(
                "sk_test",
                project_id="proj_test",
                path_suffix="/customers",
                endpoint_name="customers",
                starting_after="cus_42",
            )
        )

        called_params = mock_session.return_value.get.call_args.kwargs["params"]
        assert called_params["starting_after"] == "cus_42"
        assert called_params["limit"] == api_client.DEFAULT_PAGE_SIZE

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_immediately_when_items_missing(self, mock_session):
        # Defensive: a 200 with no `items` field should be treated as an empty
        # page rather than crashing on `None.append`.
        mock_session.return_value.get.return_value = _ok_json_response({"next_page": None})

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test", project_id="proj_test", path_suffix="/customers", endpoint_name="customers"
            )
        )

        assert rows == []

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_skips_non_dict_rows(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {"items": [{"id": "ok"}, "noise", 42], "next_page": None}
        )

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test", project_id="proj_test", path_suffix="/customers", endpoint_name="customers"
            )
        )

        assert rows == [{"id": "ok"}]

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_normalizes_created_at_from_ms_to_seconds(self, mock_session):
        # `created_at` comes back from RevenueCat as a millisecond epoch — we
        # divide by 1000 so the partition layer (which treats bare ints as Unix
        # seconds) buckets rows into the correct week.
        mock_session.return_value.get.return_value = _ok_json_response(
            {"items": [{"id": "cus_1", "created_at": 1658399423658}], "next_page": None}
        )

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test", project_id="proj_test", path_suffix="/customers", endpoint_name="customers"
            )
        )

        assert rows == [{"id": "cus_1", "created_at": 1658399423}]

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_leaves_created_at_untouched_when_missing(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"items": [{"id": "cus_1"}], "next_page": None})

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test", project_id="proj_test", path_suffix="/customers", endpoint_name="customers"
            )
        )

        assert rows == [{"id": "cus_1"}]


class TestMsToSeconds:
    def test_converts_int_milliseconds_to_seconds(self):
        assert api_client._ms_to_seconds(1658399423658) == 1658399423

    def test_passes_through_non_int_values(self):
        # Defensive: don't mangle nulls, strings, or anything else the API
        # might surprise us with — only ints get the division.
        assert api_client._ms_to_seconds(None) is None
        assert api_client._ms_to_seconds("1658399423658") == "1658399423658"

    def test_does_not_treat_bool_as_int(self):
        # `bool` subclasses `int` in Python, which would silently turn `True`
        # into `0` (1 // 1000). Make sure we don't fall into that trap.
        assert api_client._ms_to_seconds(True) is True
        assert api_client._ms_to_seconds(False) is False


class TestCreateWebhook:
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration")
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_creates_webhook_with_all_known_event_types(self, mock_session, mock_find):
        mock_find.return_value = None
        mock_session.return_value.post.return_value = _ok_json_response({"id": "wh_1"})

        result = api_client.create_webhook(
            "sk_test",
            project_id="proj_test",
            webhook_url="https://example.com/h",
            authorization_header_value="Bearer my-secret",
        )

        assert result.success is True
        # If we don't pass back the auth header value we asked for it as a
        # pending input, so this list should be empty when we supplied one
        # upfront.
        assert result.pending_inputs == []

        post_kwargs = mock_session.return_value.post.call_args.kwargs
        body = post_kwargs["json"]
        assert body["url"] == "https://example.com/h"
        assert body["name"] == REVENUECAT_AUTO_WEBHOOK_NAME
        assert set(body["events"]) == set(REVENUECAT_WEBHOOK_EVENT_TYPES)
        assert body["signing_secret"] == "Bearer my-secret"

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration")
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_treats_existing_webhook_as_success_with_pending_authorization(self, mock_session, mock_find):
        mock_find.return_value = {"id": "wh_existing", "url": "https://example.com/h"}

        result = api_client.create_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True
        assert result.pending_inputs == ["authorization_header"]
        mock_session.return_value.post.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration")
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_fails_when_existing_webhook_and_new_authorization_header_supplied(self, mock_session, mock_find):
        # RevenueCat has no in-place update for the auth header. If a webhook
        # already exists and we're asked to bind a new header, fail loudly so
        # the caller knows to delete + recreate explicitly — silently keeping
        # the existing webhook would leave it bound to a stale header value.
        mock_find.return_value = {"id": "wh_existing", "url": "https://example.com/h"}

        result = api_client.create_webhook(
            "sk_test",
            project_id="proj_test",
            webhook_url="https://example.com/h",
            authorization_header_value="Bearer my-secret",
        )

        assert result.success is False
        assert result.error is not None
        assert "already exists" in result.error.lower()
        mock_session.return_value.post.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration")
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_reports_pending_authorization_header_when_not_supplied(self, mock_session, mock_find):
        mock_find.return_value = None
        mock_session.return_value.post.return_value = _ok_json_response({"id": "wh_1"})

        result = api_client.create_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True
        assert result.pending_inputs == ["authorization_header"]

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration")
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_translates_403_into_permission_error(self, mock_session, mock_find):
        mock_find.return_value = None
        mock_session.return_value.post.return_value = _http_error_response(403)

        result = api_client.create_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is False
        assert result.error is not None
        assert "denied" in result.error.lower()


class TestDeleteWebhook:
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations")
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_deletes_matching_webhook(self, mock_session, mock_list):
        mock_list.return_value = [{"id": "wh_1", "url": "https://example.com/h"}]
        mock_session.return_value.delete.return_value = _ok_json_response()

        result = api_client.delete_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True
        called_url = mock_session.return_value.delete.call_args.args[0]
        assert called_url == f"{REVENUECAT_API_BASE_URL}/projects/proj_test/integrations/webhook/wh_1"

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations")
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_success_when_webhook_not_found(self, mock_session, mock_list):
        # Idempotent delete — missing webhook is treated as already gone, not
        # as a failure to surface to users.
        mock_list.return_value = []

        result = api_client.delete_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True
        mock_session.return_value.delete.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations")
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_404_on_delete_treated_as_success(self, mock_session, mock_list):
        mock_list.return_value = [{"id": "wh_1", "url": "https://example.com/h"}]
        mock_session.return_value.delete.return_value = _ok_json_response(status_code=404)

        result = api_client.delete_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True


class TestGetExternalWebhookInfo:
    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations")
    def test_returns_info_for_matching_webhook(self, mock_list):
        mock_list.return_value = [
            {
                "id": "wh_1",
                "url": "https://example.com/h",
                "events": ["INITIAL_PURCHASE", "RENEWAL"],
                "name": "PostHog data warehouse",
                "created_at": 1658399423658,
            }
        ]

        info = api_client.get_external_webhook_info(
            "sk_test", project_id="proj_test", webhook_url="https://example.com/h"
        )

        assert info.exists is True
        assert info.url == "https://example.com/h"
        assert info.enabled_events == ["INITIAL_PURCHASE", "RENEWAL"]
        assert info.status == "enabled"
        assert info.description == "PostHog data warehouse"

    @patch("posthog.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations")
    def test_returns_not_found_when_no_match(self, mock_list):
        mock_list.return_value = [{"id": "wh_1", "url": "https://other.example.com"}]

        info = api_client.get_external_webhook_info(
            "sk_test", project_id="proj_test", webhook_url="https://example.com/h"
        )

        assert info.exists is False


class TestProjectPath:
    def test_combines_project_id_with_suffix(self):
        assert api_client._project_path("proj_test", "/customers") == "/projects/proj_test/customers"
