import re
from collections.abc import Iterator
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import InsightVizNode

from posthog.management.commands.ensure_migration_defaults import _FEATURE_FLAG_TEMPLATE, _PRODUCT_ANALYTICS_TEMPLATE

_PLACEHOLDER = re.compile(r"^\{([A-Z0-9_]+)\}$")

_TEMPLATES = (_PRODUCT_ANALYTICS_TEMPLATE, _FEATURE_FLAG_TEMPLATE)


def _insight_tiles() -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    for template in _TEMPLATES:
        for tile in template["tiles"]:
            if tile.get("type") == "INSIGHT":
                yield f"{template['template_name']} / {tile['name']}", template, tile


def _resolve(value: Any, variables: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str):
        match = _PLACEHOLDER.match(value)
        variable = variables.get(match.group(1)) if match else None
        if variable is None:
            return value
        # Every variable is an event one, which the browser turns into a series node before the tile reaches the API.
        default = variable["default"]
        return {"kind": "EventsNode", "event": default["id"], "name": default["name"], "math": "total"}
    if isinstance(value, dict):
        return {key: _resolve(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, variables) for item in value]
    return value


def _placeholders(value: Any) -> set[str]:
    if isinstance(value, str):
        match = _PLACEHOLDER.match(value)
        return {match.group(1)} if match else set()
    if isinstance(value, dict):
        return set().union(*(_placeholders(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_placeholders(v) for v in value)) if value else set()
    return set()


class TestSeededDashboardTemplates(SimpleTestCase):
    @parameterized.expand([(label, template, tile) for label, template, tile in _insight_tiles()])
    def test_insight_tile_carries_a_query(self, _label: str, _template: dict[str, Any], tile: dict[str, Any]) -> None:
        assert tile.get("query"), "create_from_template builds insights from `query`, so a tile without one is blank"
        assert "filters" not in tile, "legacy `filters` is never read; convert with filter_to_query instead"

    @parameterized.expand([(label, template, tile) for label, template, tile in _insight_tiles()])
    def test_insight_tile_query_matches_the_schema(
        self, _label: str, template: dict[str, Any], tile: dict[str, Any]
    ) -> None:
        variables = {variable["id"]: variable for variable in template.get("variables", [])}
        InsightVizNode(**_resolve(tile["query"], variables))

    @parameterized.expand([(label, template, tile) for label, template, tile in _insight_tiles()])
    def test_placeholders_resolve_to_a_declared_variable(
        self, _label: str, template: dict[str, Any], tile: dict[str, Any]
    ) -> None:
        declared = {variable["id"] for variable in template.get("variables", [])}
        assert _placeholders(tile.get("query")) <= declared
