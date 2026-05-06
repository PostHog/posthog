from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from posthog.temporal.data_imports.sources.customer_io import api_client
from posthog.temporal.data_imports.sources.customer_io.constants import (
    CIO_AUTO_WEBHOOK_NAME,
    CIO_EU_BASE_URL,
    CIO_US_BASE_URL,
)


def _ok_json_response(payload: dict | list | None = None, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.raise_for_status = MagicMock()
    return response


class TestEventsForResources:
    def test_includes_all_known_object_type_events(self):
        events = api_client._events_for_resources(["customer_events", "email_events"])

        assert "customer_subscribed" in events
        assert "email_sent" in events
        # Order should be deterministic (customer first, then email)
        assert events.index("customer_subscribed") < events.index("email_sent")

    def test_includes_in_app_events(self):
        events = api_client._events_for_resources(["in_app_events"])

        assert "in_app_sent" in events
        assert "in_app_clicked" in events
        assert "in_app_opened" in events
        assert "in_app_converted" in events

    def test_skips_unknown_resources(self):
        events = api_client._events_for_resources(["unknown_events", "not_a_resource"])

        assert events == []

    def test_dedupes_when_resources_overlap(self):
        events_first = api_client._events_for_resources(["email_events"])
        events_second = api_client._events_for_resources(["email_events", "email_events"])

        assert events_first == events_second


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", CIO_US_BASE_URL),
            ("US", CIO_US_BASE_URL),
            ("eu", CIO_EU_BASE_URL),
            ("EU", CIO_EU_BASE_URL),
            (None, CIO_US_BASE_URL),
            ("", CIO_US_BASE_URL),
        ]
    )
    def test_picks_correct_base_url(self, region, expected):
        assert api_client._base_url(region) == expected


class TestValidateCredentials:
    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_true_on_200(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"workspaces": []})

        success, error = api_client.validate_credentials("key", "us")

        assert success is True
        assert error is None
        mock_session.return_value.get.assert_called_once()
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{CIO_US_BASE_URL}/v1/workspaces"

    @parameterized.expand(
        [
            (401, "App API Key"),
            (403, "denied"),
            (429, "rate-limited"),
            (500, "Customer.io API error"),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_false_on_http_error(self, status_code, expected_substring, mock_session):
        response = MagicMock()
        response.status_code = status_code
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        mock_session.return_value.get.return_value = response

        success, error = api_client.validate_credentials("key", "us")

        assert success is False
        assert error is not None
        assert expected_substring.lower() in error.lower()

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_false_on_network_error(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        success, error = api_client.validate_credentials("key", "us")

        assert success is False
        assert error is not None
        assert "Could not reach Customer.io" in error


class TestCreateWebhook:
    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_creates_with_correct_body(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"reporting_webhooks": []})
        mock_session.return_value.post.return_value = _ok_json_response({"id": 42})

        result = api_client.create_webhook(
            api_key="key",
            region="eu",
            webhook_url="https://example.com/hook",
            resource_names=["email_events", "customer_events"],
        )

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]
        mock_session.return_value.post.assert_called_once()
        called_url = mock_session.return_value.post.call_args.args[0]
        assert called_url == f"{CIO_EU_BASE_URL}/v1/reporting_webhooks"
        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["name"] == CIO_AUTO_WEBHOOK_NAME
        assert body["endpoint"] == "https://example.com/hook"
        assert "email_sent" in body["events"]
        assert "customer_subscribed" in body["events"]
        # Created disabled — Customer.io would 404 on webhook deliveries until the
        # signing secret is in place, so we wait until the user provides it.
        assert body["disabled"] is True

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_subscribes_to_in_app_events(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"reporting_webhooks": []})
        mock_session.return_value.post.return_value = _ok_json_response({"id": 42})

        api_client.create_webhook(
            api_key="key",
            region="us",
            webhook_url="https://example.com/hook",
            resource_names=["in_app_events"],
        )

        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert "in_app_sent" in body["events"]
        assert "in_app_clicked" in body["events"]

    @parameterized.expand(
        [
            ("disabled_existing_webhook", True),
            ("enabled_existing_webhook", False),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_skips_create_when_webhook_already_exists_for_url(self, _name, disabled, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {
                "reporting_webhooks": [
                    {
                        "id": 7,
                        "endpoint": "https://example.com/hook",
                        "events": ["email_sent"],
                        "disabled": disabled,
                    }
                ]
            }
        )

        result = api_client.create_webhook(
            api_key="key",
            region="us",
            webhook_url="https://example.com/hook",
            resource_names=["email_events"],
        )

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]
        mock_session.return_value.post.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_failure_when_no_supported_events(self, mock_session):
        result = api_client.create_webhook(
            api_key="key",
            region="us",
            webhook_url="https://example.com/hook",
            resource_names=["unknown_events", "not_a_resource"],
        )

        assert result.success is False
        assert result.error is not None
        assert "reporting-webhook" in result.error
        mock_session.return_value.get.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_surfaces_http_error_as_failure(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"reporting_webhooks": []})
        response = MagicMock()
        response.status_code = 401
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        mock_session.return_value.post.return_value = response

        result = api_client.create_webhook(
            api_key="key",
            region="us",
            webhook_url="https://example.com/hook",
            resource_names=["email_events"],
        )

        assert result.success is False
        assert result.error is not None
        assert "App API Key" in result.error


class TestEnableWebhook:
    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_enables_disabled_webhook(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {
                "reporting_webhooks": [
                    {"id": 7, "endpoint": "https://example.com/hook", "disabled": True},
                ]
            }
        )
        mock_session.return_value.put.return_value = _ok_json_response()

        success, error = api_client.enable_webhook("key", "us", "https://example.com/hook")

        assert success is True
        assert error is None
        mock_session.return_value.put.assert_called_once()
        called_url = mock_session.return_value.put.call_args.args[0]
        assert called_url == f"{CIO_US_BASE_URL}/v1/reporting_webhooks/7"
        body = mock_session.return_value.put.call_args.kwargs["json"]
        assert body == {"disabled": False}

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_noop_when_already_enabled(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {"reporting_webhooks": [{"id": 7, "endpoint": "https://example.com/hook", "disabled": False}]}
        )

        success, error = api_client.enable_webhook("key", "us", "https://example.com/hook")

        assert success is True
        assert error is None
        mock_session.return_value.put.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_failure_when_webhook_not_found(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"reporting_webhooks": []})

        success, error = api_client.enable_webhook("key", "us", "https://example.com/hook")

        assert success is False
        assert error is not None
        assert "No reporting webhook" in error
        mock_session.return_value.put.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_failure_on_put_http_error(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {"reporting_webhooks": [{"id": 7, "endpoint": "https://example.com/hook", "disabled": True}]}
        )
        response = MagicMock()
        response.status_code = 401
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        mock_session.return_value.put.return_value = response

        success, error = api_client.enable_webhook("key", "us", "https://example.com/hook")

        assert success is False
        assert error is not None
        assert "App API Key" in error

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_failure_on_network_error(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        success, error = api_client.enable_webhook("key", "us", "https://example.com/hook")

        assert success is False
        assert error is not None
        assert "Could not reach Customer.io" in error


class TestDeleteWebhook:
    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_deletes_matching_webhook(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {
                "reporting_webhooks": [
                    {"id": 1, "endpoint": "https://other.example.com/hook"},
                    {"id": 7, "endpoint": "https://example.com/hook"},
                ]
            }
        )
        mock_session.return_value.delete.return_value = _ok_json_response(status_code=204)

        result = api_client.delete_webhook("key", "us", "https://example.com/hook")

        assert result.success is True
        called_url = mock_session.return_value.delete.call_args.args[0]
        assert called_url == f"{CIO_US_BASE_URL}/v1/reporting_webhooks/7"

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_success_when_webhook_not_found(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"reporting_webhooks": []})

        result = api_client.delete_webhook("key", "us", "https://example.com/hook")

        assert result.success is True
        mock_session.return_value.delete.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_treats_404_on_delete_as_success(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {"reporting_webhooks": [{"id": 7, "endpoint": "https://example.com/hook"}]}
        )
        delete_response = MagicMock()
        delete_response.status_code = 404
        delete_response.raise_for_status = MagicMock()
        mock_session.return_value.delete.return_value = delete_response

        result = api_client.delete_webhook("key", "us", "https://example.com/hook")

        assert result.success is True

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_failure_on_list_error(self, mock_session):
        response = MagicMock()
        response.status_code = 401
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        mock_session.return_value.get.return_value = response

        result = api_client.delete_webhook("key", "us", "https://example.com/hook")

        assert result.success is False
        assert result.error is not None
        assert "App API Key" in result.error


class TestGetExternalWebhookInfo:
    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_exists_true_when_url_matches(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {
                "reporting_webhooks": [
                    {
                        "id": 7,
                        "endpoint": "https://example.com/hook",
                        "events": ["email_sent", "email_delivered"],
                        "name": "Hook name",
                        "disabled": False,
                    }
                ]
            }
        )

        info = api_client.get_external_webhook_info("key", "us", "https://example.com/hook")

        assert info.exists is True
        assert info.url == "https://example.com/hook"
        assert info.enabled_events == ["email_sent", "email_delivered"]
        assert info.status == "enabled"
        assert info.description == "Hook name"

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_exists_false_when_no_match(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"reporting_webhooks": []})

        info = api_client.get_external_webhook_info("key", "us", "https://example.com/hook")

        assert info.exists is False
        assert info.error is None

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_marks_disabled_webhook(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {"reporting_webhooks": [{"id": 1, "endpoint": "https://example.com/hook", "disabled": True, "events": []}]}
        )

        info = api_client.get_external_webhook_info("key", "us", "https://example.com/hook")

        assert info.exists is True
        assert info.status == "disabled"

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_returns_error_on_unauthorized(self, mock_session):
        response = MagicMock()
        response.status_code = 401
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        mock_session.return_value.get.return_value = response

        info = api_client.get_external_webhook_info("key", "us", "https://example.com/hook")

        assert info.exists is False
        assert info.error is not None
        assert "App API Key" in info.error


class TestIterateListEndpoint:
    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_yields_rows_from_single_page_endpoint(self, mock_session):
        from posthog.temporal.data_imports.sources.customer_io.constants import CIO_API_ENDPOINTS

        endpoint = CIO_API_ENDPOINTS["broadcasts"]
        mock_session.return_value.get.return_value = _ok_json_response(
            {"broadcasts": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}
        )

        rows = list(api_client.iterate_list_endpoint("key", "us", endpoint))

        assert rows == [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        mock_session.return_value.get.assert_called_once()
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{CIO_US_BASE_URL}/v1/broadcasts"

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_follows_cursor_pagination(self, mock_session):
        from posthog.temporal.data_imports.sources.customer_io.constants import CIO_API_ENDPOINTS

        endpoint = CIO_API_ENDPOINTS["newsletters"]
        mock_session.return_value.get.side_effect = [
            _ok_json_response({"newsletters": [{"id": 1}], "next": "cursor-2"}),
            _ok_json_response({"newsletters": [{"id": 2}], "next": "cursor-3"}),
            _ok_json_response({"newsletters": [{"id": 3}]}),  # no `next` -> stop
        ]

        rows = list(api_client.iterate_list_endpoint("key", "us", endpoint))

        assert [row["id"] for row in rows] == [1, 2, 3]
        assert mock_session.return_value.get.call_count == 3
        # Second call should pass the cursor from the first response
        second_params = mock_session.return_value.get.call_args_list[1].kwargs["params"]
        assert second_params["start"] == "cursor-2"
        assert second_params["limit"] == endpoint.page_size

    @patch("posthog.temporal.data_imports.sources.customer_io.api_client._session")
    def test_skips_non_dict_rows(self, mock_session):
        from posthog.temporal.data_imports.sources.customer_io.constants import CIOListEndpoint

        endpoint = CIOListEndpoint(
            path="/v1/things",
            response_key="things",
            primary_keys=["id"],
            partition_keys=["id"],
            partition_mode="md5",
        )
        mock_session.return_value.get.return_value = _ok_json_response(
            {"things": [{"id": 1}, "garbage", None, {"id": 2}]}
        )

        rows = list(api_client.iterate_list_endpoint("key", "us", endpoint))

        assert rows == [{"id": 1}, {"id": 2}]
