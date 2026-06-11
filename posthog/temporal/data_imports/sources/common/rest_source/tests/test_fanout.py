from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import Mock, patch

from posthog.temporal.data_imports.sources.common.rest_source import _make_paginate_dependent_resource
from posthog.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_dependent_resource,
)
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import ResolvedParam


@dataclass
class _EndpointConfig:
    name: str
    path: str
    incremental_fields: list[Any]
    default_incremental_field: str | None = None
    page_size: int = 100


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
        ),
        "children": _EndpointConfig(
            name="children",
            path="/parents/{parent_id}/children",
            incremental_fields=[],
            page_size=7,
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


def test_paginate_dependent_resource_does_not_leak_params_across_parents() -> None:
    captured_initial_params: list[dict[str, Any]] = []

    def fake_paginate(**kwargs):
        params = kwargs["params"]
        # Snapshot the params as they arrive for the first page of each parent
        captured_initial_params.append(dict(params))
        # Page 1: return data with original params
        yield [{"id": "child_1", "token": "tok_page1"}]
        # Between pages the real paginator mutates params (removes since/until, adds before)
        params.pop("since", None)
        params.pop("until", None)
        params["before"] = "tok_page1"
        # Page 2: return data with mutated params
        yield [{"id": "child_2", "token": "tok_page2"}]

    mock_client = Mock()
    mock_client.paginate = fake_paginate

    resolved_param = ResolvedParam(
        param_name="parent_id",
        resolve_config={"type": "resolve", "resource": "parents", "field": "id"},
    )

    paginate_fn = _make_paginate_dependent_resource(
        client=mock_client,
        resolved_param=resolved_param,
        include_from_parent=[],
        default_columns_config=None,
        incremental_object=None,
        incremental_param=None,
        incremental_cursor_transform=None,
        db_incremental_field_last_value=None,
    )

    results: list[list[dict[str, Any]]] = []
    for page in paginate_fn(
        items=[{"id": "parent_a"}, {"id": "parent_b"}],
        method="get",
        path="/parents/{parent_id}/children",
        params={"page_size": 100, "since": "2026-01-01", "until": "2026-03-01"},
        paginator=None,
        data_selector="items",
        hooks=None,
    ):
        if isinstance(page, list):
            results.append(page)

    assert len(captured_initial_params) == 2
    # Parent B's first request must have the original since/until,
    # not the before token left over from parent A's page 2
    for params_snapshot in captured_initial_params:
        assert params_snapshot["since"] == "2026-01-01"
        assert params_snapshot["until"] == "2026-03-01"
        assert "before" not in params_snapshot
