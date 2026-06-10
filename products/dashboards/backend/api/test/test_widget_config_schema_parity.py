from posthog.test.base import BaseTest

from products.dashboards.backend.constants import DEFAULT_WIDGET_LIST_LIMIT
from products.dashboards.backend.widget_catalog import WIDGET_CATALOG
from products.dashboards.backend.widget_specs.registry import WIDGET_SPECS


class TestWidgetConfigSchemaParity(BaseTest):
    def test_catalog_config_schema_matches_pydantic_models(self) -> None:
        for widget_type, entry in WIDGET_CATALOG.items():
            spec = WIDGET_SPECS[widget_type]
            pydantic_schema = spec.config_model.model_json_schema(mode="serialization")
            assert entry["config_schema"] == pydantic_schema

    def test_widget_config_limit_constraints_match_ssot(self) -> None:
        for widget_type, spec in WIDGET_SPECS.items():
            limit_schema = spec.config_model.model_json_schema(mode="serialization")["properties"]["limit"]
            assert limit_schema["minimum"] == 1
            assert limit_schema["maximum"] == 25
            assert limit_schema["default"] == DEFAULT_WIDGET_LIST_LIMIT
            catalog_limit = WIDGET_CATALOG[widget_type]["config_schema"]["properties"]["limit"]
            assert catalog_limit == limit_schema
