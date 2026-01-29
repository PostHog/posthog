"""
Tests for the REST source to capture existing behavior before refactoring.

This test suite ensures that when we replace DLT's REST client with our own
implementation, we maintain the same external API and behavior.
"""

import json
from typing import Any, Optional

import responses
from requests import Request, Response

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.pagination import (
    BasePaginator,
    OffsetPaginator,
    PageNumberPaginator,
)


class TestPagination:
    """Test different pagination strategies."""

    @responses.activate
    def test_offset_pagination(self):
        """Test offset-based pagination."""
        # Mock API responses with 3 pages
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"items": [{"id": 1}, {"id": 2}], "total": 5},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"items": [{"id": 3}, {"id": 4}], "total": 5},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"items": [{"id": 5}], "total": 5},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "paginator": OffsetPaginator(limit=2, offset_param="offset", limit_param="limit", total_path="total"),
            },
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "items",
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 5
        assert items[0]["id"] == 1
        assert items[4]["id"] == 5

        # Verify pagination params in requests
        assert len(responses.calls) == 3
        assert "offset=0" in responses.calls[0].request.url
        assert "limit=2" in responses.calls[0].request.url
        assert "offset=2" in responses.calls[1].request.url
        assert "offset=4" in responses.calls[2].request.url

    @responses.activate
    def test_page_number_pagination(self):
        """Test page number-based pagination."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 1}, {"id": 2}], "page": 1, "total_pages": 2},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 3}], "page": 2, "total_pages": 2},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "paginator": PageNumberPaginator(page_param="page", total_path="total_pages"),
            },
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "data",
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 3
        assert items[0]["id"] == 1
        assert items[2]["id"] == 3

    @responses.activate
    def test_json_response_cursor_pagination(self):
        """Test cursor-based pagination using JSON response."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 1}, {"id": 2}], "next_cursor": "cursor_abc"},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 3}], "next_cursor": None},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "paginator": {
                    "type": "cursor",
                    "cursor_path": "next_cursor",
                    "cursor_param": "cursor",
                },
            },
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "data",
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 3
        assert "cursor=cursor_abc" in responses.calls[1].request.url

    @responses.activate
    def test_custom_paginator(self):
        """Test using a custom paginator class."""

        class CustomPaginator(BasePaginator):
            def __init__(self):
                super().__init__()
                self.page = 0

            def update_state(self, response: Response, data: Optional[Any] = None) -> None:
                try:
                    json_data = response.json()
                    self._has_next_page = json_data.get("has_more", False)
                    self.page += 1
                except Exception:
                    self._has_next_page = False

            def update_request(self, request: Request) -> None:
                if request.params is None:
                    request.params = {}
                request.params["page"] = self.page

        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"items": [{"id": 1}, {"id": 2}], "has_more": True},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"items": [{"id": 3}], "has_more": False},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "paginator": CustomPaginator(),
            },
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "items",
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 3


class TestAuthentication:
    """Test different authentication methods."""

    @responses.activate
    def test_bearer_token_auth(self):
        """Test Bearer token authentication."""
        base_url = "https://api.example.com"
        token = "test_token_123"

        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 1}]},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "auth": {
                    "type": "bearer",
                    "token": token,
                },
            },
            "resources": ["items"],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        list(resource)

        # Verify Bearer token in request
        assert responses.calls[0].request.headers["Authorization"] == f"Bearer {token}"

    @responses.activate
    def test_http_basic_auth(self):
        """Test HTTP Basic authentication."""
        base_url = "https://api.example.com"
        username = "user"
        password = "pass"

        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 1}]},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "auth": {
                    "type": "http_basic",
                    "username": username,
                    "password": password,
                },
            },
            "resources": ["items"],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        list(resource)

        # Verify Basic auth header
        assert "Authorization" in responses.calls[0].request.headers
        assert responses.calls[0].request.headers["Authorization"].startswith("Basic ")

    @responses.activate
    def test_api_key_auth(self):
        """Test API key authentication."""
        base_url = "https://api.example.com"
        api_key = "key_123"

        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 1}]},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "auth": {
                    "type": "api_key",
                    "api_key": api_key,
                    "location": "header",
                    "name": "X-API-Key",
                },
            },
            "resources": ["items"],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        list(resource)

        # Verify API key in header
        assert responses.calls[0].request.headers["X-API-Key"] == api_key


class TestDataExtraction:
    """Test JSONPath data extraction."""

    @responses.activate
    def test_data_selector_simple(self):
        """Test simple data selector."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 1}, {"id": 2}]},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "data",
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 2
        assert items[0]["id"] == 1

    @responses.activate
    def test_data_selector_nested(self):
        """Test nested data selector."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"response": {"results": {"items": [{"id": 1}, {"id": 2}]}}},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "response.results.items",
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 2

    @responses.activate
    def test_data_selector_array_wildcard(self):
        """Test data selector with array wildcard."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"item": {"id": 1}}, {"item": {"id": 2}}]},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "data[*].item",
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 2
        assert items[0]["id"] == 1


class TestIncrementalLoading:
    """Test incremental loading with cursor tracking."""

    @responses.activate
    def test_incremental_with_initial_value(self):
        """Test incremental loading with initial value."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 1, "updated_at": 100}, {"id": 2, "updated_at": 200}]},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "data",
                        "params": {
                            "since": {
                                "type": "incremental",
                                "cursor_path": "updated_at",
                                "initial_value": 0,
                            },
                        },
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 2
        # Verify initial value was used
        assert "since=0" in responses.calls[0].request.url

    @responses.activate
    def test_incremental_with_transform(self):
        """Test incremental loading with value transformation."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 1, "created": "2024-01-01"}]},
            status=200,
        )

        # Transform ISO date to timestamp
        def date_to_timestamp(date_str):
            return int(date_str.replace("-", ""))

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "data",
                        "params": {
                            "since": {
                                "type": "incremental",
                                "cursor_path": "created",
                                "initial_value": "2024-01-01",
                                "convert": date_to_timestamp,
                            },
                        },
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 1

    @responses.activate
    def test_incremental_resume_from_db(self):
        """Test incremental loading resuming from database value."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": [{"id": 3, "updated_at": 300}]},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "data",
                        "params": {
                            "since": {
                                "type": "incremental",
                                "cursor_path": "updated_at",
                                "initial_value": 0,
                            },
                        },
                    },
                }
            ],
        }

        # Resume from previously saved value
        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=200)
        items = list(resource)

        assert len(items) == 1
        # Should use the DB value, not initial value
        assert "since=200" in responses.calls[0].request.url


class TestResourceConfiguration:
    """Test resource configuration and merging."""

    @responses.activate
    def test_resource_defaults(self):
        """Test that resource defaults are applied."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json=[{"id": 1}],
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resource_defaults": {
                "primary_key": "id",
                "write_disposition": "merge",
            },
            "resources": ["items"],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)

        # Verify resource is created successfully
        assert resource is not None

    @responses.activate
    def test_resource_string_shorthand(self):
        """Test that string resources work as shorthand."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json=[{"id": 1}],
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": ["items"],  # String shorthand
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 1
        assert "items" in responses.calls[0].request.url

    @responses.activate
    def test_multiple_resources(self):
        """Test that first resource is returned when multiple are configured."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/users",
            json=[{"id": 1}],
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": ["users", "orders"],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        users = list(resource)

        assert len(users) == 1

    @responses.activate
    def test_request_params(self):
        """Test that request parameters are included."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json=[{"id": 1}],
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "params": {
                            "status": "active",
                            "limit": 100,
                        },
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        list(resource)

        # Verify params in request
        url = responses.calls[0].request.url
        assert "status=active" in url
        assert "limit=100" in url

    @responses.activate
    def test_post_request_with_json_body(self):
        """Test POST requests with JSON body."""
        base_url = "https://api.example.com"
        responses.add(
            responses.POST,
            f"{base_url}/query",
            json={"results": [{"id": 1}]},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": [
                {
                    "name": "query_results",
                    "endpoint": {
                        "path": "query",
                        "method": "POST",
                        "json": {
                            "query": "SELECT * FROM items",
                        },
                        "data_selector": "results",
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 1
        # Verify POST method and body
        assert responses.calls[0].request.method == "POST"
        body = json.loads(responses.calls[0].request.body)
        assert body["query"] == "SELECT * FROM items"


class TestEdgeCases:
    """Test edge cases and error handling."""

    @responses.activate
    def test_empty_response(self):
        """Test handling empty responses."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json={"data": []},
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {"base_url": base_url},
            "resources": [
                {
                    "name": "items",
                    "endpoint": {
                        "path": "items",
                        "data_selector": "data",
                    },
                }
            ],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 0

    @responses.activate
    def test_single_page_no_pagination(self):
        """Test single page response without pagination."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json=[{"id": 1}, {"id": 2}],
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "paginator": "single_page",
            },
            "resources": ["items"],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        items = list(resource)

        assert len(items) == 2
        # Should only make one request
        assert len(responses.calls) == 1

    @responses.activate
    def test_custom_headers(self):
        """Test custom headers are included in requests."""
        base_url = "https://api.example.com"
        responses.add(
            responses.GET,
            f"{base_url}/items",
            json=[{"id": 1}],
            status=200,
        )

        config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "headers": {
                    "User-Agent": "PostHog/1.0",
                    "X-Custom-Header": "value",
                },
            },
            "resources": ["items"],
        }

        resource = rest_api_resources(config, team_id=1, job_id="test-job", db_incremental_field_last_value=None)
        list(resource)

        # Verify headers
        headers = responses.calls[0].request.headers
        assert headers["User-Agent"] == "PostHog/1.0"
        assert headers["X-Custom-Header"] == "value"
