from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import patch

from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_dependent_resource,
)


@dataclass
class _EndpointConfig:
    name: str
    path: str
    incremental_fields: list[Any]
    default_incremental_field: str | None = None
    page_size: int = 100
    primary_key: str | list[str] = "id"


class _DummyPaginator(BasePaginator):
    def update_state(self, response, data=None) -> None:
        self._has_next_page = False

    def update_request(self, request) -> None:
        return None


def _build_endpoint_configs() -> dict[str, _EndpointConfig]:
    return {
        "parents": _EndpointConfig(
            name="parents",
            path="/parents",
            incremental_fields=[],
            page_size=3,
            primary_key="id",
        ),
        "children": _EndpointConfig(
            name="children",
            path="/parents/{parent_id}/children",
            incremental_fields=[],
            page_size=7,
            primary_key=["parent_id", "id"],
        ),
    }


@patch("posthog.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_build_dependent_resource_uses_custom_page_size_param(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []
    try:
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=DependentEndpointConfig(
                parent_name="parents",
                resolve_param="parent_id",
                resolve_field="id",
                include_from_parent=["id"],
            ),
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            page_size_param="page_size",
        )
    except StopIteration:
        pass

    config = mock_rest_api_resources.call_args.args[0]
    parent_resource = config["resources"][0]
    child_resource = config["resources"][1]
    assert parent_resource["endpoint"]["params"]["page_size"] == 3
    assert child_resource["endpoint"]["params"]["page_size"] == 7
    assert "limit" not in parent_resource["endpoint"]["params"]
    assert "limit" not in child_resource["endpoint"]["params"]


@patch("posthog.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_build_dependent_resource_forwards_endpoint_extras(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []
    try:
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=DependentEndpointConfig(
                parent_name="parents",
                resolve_param="parent_id",
                resolve_field="id",
                include_from_parent=["id"],
            ),
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": "items", "paginator": _DummyPaginator()},
            child_endpoint_extra={"data_selector": "items", "paginator": _DummyPaginator()},
        )
    except StopIteration:
        pass

    config = mock_rest_api_resources.call_args.args[0]
    parent_endpoint = config["resources"][0]["endpoint"]
    child_endpoint = config["resources"][1]["endpoint"]
    assert parent_endpoint["data_selector"] == "items"
    assert child_endpoint["data_selector"] == "items"
    assert isinstance(parent_endpoint["paginator"], _DummyPaginator)
    assert isinstance(child_endpoint["paginator"], _DummyPaginator)


@patch("posthog.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_build_dependent_resource_backwards_compatible_defaults(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []
    try:
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=DependentEndpointConfig(
                parent_name="parents",
                resolve_param="parent_id",
                resolve_field="id",
                include_from_parent=["id"],
            ),
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
        )
    except StopIteration:
        pass

    config = mock_rest_api_resources.call_args.args[0]
    parent_resource = config["resources"][0]
    child_resource = config["resources"][1]
    assert parent_resource["endpoint"]["params"]["limit"] == 3
    assert child_resource["endpoint"]["params"]["limit"] == 7
    assert "data_selector" not in parent_resource["endpoint"]
    assert "data_selector" not in child_resource["endpoint"]


@patch("posthog.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
def test_build_dependent_resource_rejects_params_in_endpoint_extras(mock_rest_api_resources) -> None:
    mock_rest_api_resources.return_value = []

    with pytest.raises(ValueError, match="Do not pass 'params' in child_endpoint_extra"):
        build_dependent_resource(
            endpoint_configs=_build_endpoint_configs(),
            child_endpoint="children",
            fanout=DependentEndpointConfig(
                parent_name="parents",
                resolve_param="parent_id",
                resolve_field="id",
                include_from_parent=["id"],
            ),
            client_config={"base_url": "https://example.com"},
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            child_endpoint_extra={"params": {"limit": 1}},
        )
