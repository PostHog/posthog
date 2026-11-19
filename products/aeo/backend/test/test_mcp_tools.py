from pathlib import Path

from django.test import SimpleTestCase

import yaml
from drf_spectacular.generators import EndpointEnumerator, SchemaGenerator

TOOLS_YAML = Path(__file__).parents[2] / "mcp" / "tools.yaml"


class _AEOEndpointEnumerator(EndpointEnumerator):
    def should_include_endpoint(self, path, callback, *args, **kwargs):
        view_class = getattr(callback, "cls", None)
        if view_class is None or not view_class.__module__.startswith("products.aeo."):
            return False
        return super().should_include_endpoint(path, callback, *args, **kwargs)


class _AEOSchemaGenerator(SchemaGenerator):
    endpoint_inspector_cls = _AEOEndpointEnumerator


class TestMCPTools(SimpleTestCase):
    def test_every_api_operation_has_an_mcp_tool_entry(self) -> None:
        schema = _AEOSchemaGenerator().get_schema(request=None, public=True)
        operations = {
            operation["operationId"]
            for path_item in schema["paths"].values()
            for operation in path_item.values()
            if isinstance(operation, dict) and "operationId" in operation
        }
        configured = {tool["operation"] for tool in yaml.safe_load(TOOLS_YAML.read_text())["tools"].values()}

        assert operations, "found no AI visibility API operations, so the enumerator no longer matches the viewsets"
        missing = sorted(operations - configured)
        assert not missing, (
            f"AI visibility API operations without an MCP tool entry: {missing}. Agents should reach every feature "
            "through MCP, so add one with `pnpm --filter=@posthog/mcp run scaffold-yaml -- --add <operationId> "
            "--product aeo`, or record why it stays off with `enabled: false` and a `disabled_reason`."
        )
