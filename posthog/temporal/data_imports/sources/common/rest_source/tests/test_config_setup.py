from typing import Any, cast

import pytest

from posthog.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth, BearerTokenAuth, HttpBasicAuth
from posthog.temporal.data_imports.sources.common.rest_source.config_setup import (
    Incremental,
    IncrementalParam,
    _merge_resource_endpoints,
    create_auth,
    create_paginator,
    setup_incremental_object,
)
from posthog.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from posthog.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    EndpointResourceBase,
    IncrementalConfig,
)


class TestCreatePaginator:
    def test_string_config(self) -> None:
        assert isinstance(create_paginator("single_page"), SinglePagePaginator)
        assert isinstance(create_paginator("header_link"), HeaderLinkPaginator)
        assert isinstance(create_paginator("json_response"), JSONResponsePaginator)
        assert isinstance(create_paginator("cursor"), JSONResponseCursorPaginator)

    def test_auto_returns_none(self) -> None:
        assert create_paginator("auto") is None

    def test_none_returns_none(self) -> None:
        assert create_paginator(None) is None

    def test_dict_config(self) -> None:
        p = create_paginator({"type": "offset", "limit": 50})
        assert isinstance(p, OffsetPaginator)
        assert p.limit == 50

    def test_instance_passthrough(self) -> None:
        p = SinglePagePaginator()
        assert create_paginator(p) is p

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid paginator"):
            create_paginator(cast(Any, "nonexistent"))


class TestCreateAuth:
    def test_bearer_from_dict(self) -> None:
        auth = create_auth({"type": "bearer", "token": "my-token"})
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "my-token"

    def test_api_key_from_dict(self) -> None:
        auth = create_auth({"type": "api_key", "api_key": "key123", "name": "X-Api-Key"})
        assert isinstance(auth, APIKeyAuth)
        assert auth.api_key == "key123"
        assert auth.name == "X-Api-Key"

    def test_http_basic_from_dict(self) -> None:
        auth = create_auth({"type": "http_basic", "username": "user", "password": "pass"})
        assert isinstance(auth, HttpBasicAuth)

    def test_none_returns_none(self) -> None:
        assert create_auth(None) is None

    def test_instance_passthrough(self) -> None:
        auth = BearerTokenAuth(token="tok")
        assert create_auth(auth) is auth


class TestSetupIncrementalObject:
    def test_from_params(self) -> None:
        params = {
            "since": {
                "type": "incremental",
                "cursor_path": "updated_at",
                "initial_value": "2024-01-01",
            }
        }
        inc, param, convert = setup_incremental_object(params)
        assert isinstance(inc, Incremental)
        assert inc.cursor_path == "updated_at"
        assert inc.initial_value == "2024-01-01"
        assert param == IncrementalParam(start="since", end=None)

    def test_from_config(self) -> None:
        params: dict = {}
        config: IncrementalConfig = {
            "cursor_path": "modified",
            "initial_value": "2024-01-01",
            "start_param": "start",
            "end_param": "end",
        }
        inc, param, convert = setup_incremental_object(params, config)
        assert isinstance(inc, Incremental)
        assert param == IncrementalParam(start="start", end="end")

    def test_no_incremental(self) -> None:
        params = {"limit": 100}
        inc, param, convert = setup_incremental_object(params)
        assert inc is None
        assert param is None

    def test_multiple_incremental_raises(self) -> None:
        params = {
            "since": {"type": "incremental", "cursor_path": "a", "initial_value": "x"},
            "until": {"type": "incremental", "cursor_path": "b", "initial_value": "y"},
        }
        with pytest.raises(ValueError, match="Only a single incremental"):
            setup_incremental_object(params)


class TestMergeResourceEndpoints:
    def test_default_params_merged_with_resource_params(self) -> None:
        """Default ``endpoint.params`` must be merged with resource-level params,
        not dropped when the resource also defines params."""
        default: EndpointResourceBase = {"endpoint": {"params": {"limit": 100, "page_size": 25}}}
        resource: EndpointResource = {"endpoint": {"params": {"since": "2024-01-01"}}}

        merged = _merge_resource_endpoints(default, resource)

        endpoint = cast(Endpoint, merged["endpoint"])
        assert endpoint["params"] == {
            "limit": 100,
            "page_size": 25,
            "since": "2024-01-01",
        }

    def test_resource_params_override_default_params(self) -> None:
        default: EndpointResourceBase = {"endpoint": {"params": {"limit": 100}}}
        resource: EndpointResource = {"endpoint": {"params": {"limit": 50}}}

        merged = _merge_resource_endpoints(default, resource)

        endpoint = cast(Endpoint, merged["endpoint"])
        assert endpoint["params"] == {"limit": 50}

    def test_default_json_and_params_are_independent(self) -> None:
        """Merging ``params`` must not be affected by default ``json`` and
        vice versa."""
        default: EndpointResourceBase = {"endpoint": {"json": {"a": 1}, "params": {"limit": 100}}}
        resource: EndpointResource = {"endpoint": {"json": {"b": 2}, "params": {"since": "x"}}}

        merged = _merge_resource_endpoints(default, resource)

        endpoint = cast(Endpoint, merged["endpoint"])
        assert endpoint["params"] == {"limit": 100, "since": "x"}
        assert endpoint["json"] == {"a": 1, "b": 2}
