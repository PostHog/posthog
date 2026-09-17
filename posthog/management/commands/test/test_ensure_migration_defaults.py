import re
from collections.abc import Iterator
from io import StringIO
from typing import Any

from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from oauth2_provider.settings import oauth2_settings
from parameterized import parameterized

from posthog.schema import InsightVizNode

from posthog.management.commands.ensure_migration_defaults import (
    _FEATURE_FLAG_TEMPLATE,
    _PRODUCT_ANALYTICS_TEMPLATE,
    _STREAMLIT_OAUTH_CLIENT_ID,
)
from posthog.models.oauth import OAuthApplication

from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

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


class TestEnsureMigrationDefaults(TestCase):
    @parameterized.expand([("with an OIDC key", "-----FAKE KEY-----", True), ("without an OIDC key", "", False)])
    def test_seeds_every_default_and_creates_the_oauth_app_only_when_rs256_can_sign(
        self, _label: str, oidc_key: str, expects_oauth_app: bool
    ) -> None:
        OAuthApplication.objects.filter(client_id=_STREAMLIT_OAUTH_CLIENT_ID).delete()
        template_name = _PRODUCT_ANALYTICS_TEMPLATE["template_name"]
        DashboardTemplate.objects.filter(template_name=template_name, team__isnull=True).delete()

        with patch.object(oauth2_settings, "OIDC_RSA_PRIVATE_KEY", oidc_key):
            call_command("ensure_migration_defaults", stdout=StringIO())

        assert OAuthApplication.objects.filter(client_id=_STREAMLIT_OAUTH_CLIENT_ID).exists() is expects_oauth_app
        # Seeded after the OAuth app, so its presence proves the command ran to the end.
        assert DashboardTemplate.objects.filter(template_name=template_name, team__isnull=True).exists()
