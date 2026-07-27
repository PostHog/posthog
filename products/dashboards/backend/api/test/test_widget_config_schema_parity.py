from posthog.test.base import BaseTest

from products.dashboards.backend.constants import (
    ACTIVITY_EVENTS_DEFAULT_LIMIT,
    ACTIVITY_EVENTS_MAX_LIMIT,
    DEFAULT_WIDGET_LIST_LIMIT,
    LOGS_LIST_DEFAULT_LIMIT,
    LOGS_LIST_MAX_LIMIT,
    MAX_WIDGET_RESULT_LIMIT,
)
from products.dashboards.backend.widget_catalog import WIDGET_CATALOG
from products.dashboards.backend.widget_specs.configs import ACTIVITY_EVENTS_LIST_WIDGET_TYPE, LOGS_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import WIDGET_SPECS

# Activity events and logs allow a larger page than other list widgets; other types share the default bounds.
WIDGET_LIMIT_BOUNDS = {
    ACTIVITY_EVENTS_LIST_WIDGET_TYPE: (ACTIVITY_EVENTS_MAX_LIMIT, ACTIVITY_EVENTS_DEFAULT_LIMIT),
    LOGS_LIST_WIDGET_TYPE: (LOGS_LIST_MAX_LIMIT, LOGS_LIST_DEFAULT_LIMIT),
}


class TestWidgetConfigSchemaParity(BaseTest):
    def test_catalog_config_schema_matches_pydantic_models(self) -> None:
        for widget_type, entry in WIDGET_CATALOG.items():
            spec = WIDGET_SPECS[widget_type]
            pydantic_schema = spec.config_model.model_json_schema(mode="serialization")
            assert entry["config_schema"] == pydantic_schema

    def test_widget_config_limit_constraints_match_ssot(self) -> None:
        for widget_type, spec in WIDGET_SPECS.items():
            properties = spec.config_model.model_json_schema(mode="serialization")["properties"]
            if "limit" not in properties:
                # Non-list widgets (e.g. experiment_results) have no row limit.
                continue
            expected_max, expected_default = WIDGET_LIMIT_BOUNDS.get(
                widget_type, (MAX_WIDGET_RESULT_LIMIT, DEFAULT_WIDGET_LIST_LIMIT)
            )
            limit_schema = properties["limit"]
            assert limit_schema["minimum"] == 1
            assert limit_schema["maximum"] == expected_max
            assert limit_schema["default"] == expected_default
            catalog_limit = WIDGET_CATALOG[widget_type]["config_schema"]["properties"]["limit"]
            assert catalog_limit == limit_schema
