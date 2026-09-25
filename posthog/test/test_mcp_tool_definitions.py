import json
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from posthog.mcp_tool_definitions import get_mcp_tool_definitions, mcp_tool_required_scopes

_SCHEMA_DIR = Path(settings.BASE_DIR) / "services" / "mcp" / "schema"


def _raw(file_name: str) -> dict:
    return json.loads((_SCHEMA_DIR / file_name).read_text())


def _definition(**overrides) -> dict:
    return {
        "title": "Tool",
        "summary": "A tool.",
        "description": "A tool.",
        "category": "Testing",
        "feature": "testing",
        "required_scopes": [],
        "annotations": {
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "readOnlyHint": True,
        },
        **overrides,
    }


class TestMcpToolDefinitions(SimpleTestCase):
    def setUp(self) -> None:
        get_mcp_tool_definitions.cache_clear()
        mcp_tool_required_scopes.cache_clear()
        self.addCleanup(get_mcp_tool_definitions.cache_clear)
        self.addCleanup(mcp_tool_required_scopes.cache_clear)

    def test_merges_by_tool_name_with_the_generated_definition_winning(self) -> None:
        # The MCP server's getToolDefinitions() keyed merge drops the overridden definition, so a
        # catalogue built the other way round describes a tool the server does not serve, and
        # advertises consent scopes no active tool requires.
        with TemporaryDirectory() as tmp_dir:
            handwritten = Path(tmp_dir) / "handwritten.json"
            generated = Path(tmp_dir) / "generated.json"
            handwritten.write_text(
                json.dumps(
                    {
                        "shared": _definition(summary="Overridden.", required_scopes=["overridden:read"]),
                        "hand-written-only": _definition(required_scopes=["hand_written:read"]),
                    }
                )
            )
            generated.write_text(
                json.dumps({"shared": _definition(summary="Active.", required_scopes=["active:read"])})
            )

            with patch("posthog.mcp_tool_definitions._TOOL_DEFINITION_PATHS", (handwritten, generated)):
                definitions = get_mcp_tool_definitions()

                assert definitions["shared"].summary == "Active."
                assert definitions["shared"].required_scopes == ("active:read",)
                assert definitions["hand-written-only"].required_scopes == ("hand_written:read",)
                assert mcp_tool_required_scopes() == frozenset({"active:read", "hand_written:read"})

    def test_reads_the_real_committed_catalog(self) -> None:
        # Guards the cross-service artifact paths and shape: if the files under
        # services/mcp/schema/ move or change structure, this fails loudly instead of leaving
        # every caller with an empty catalogue.
        handwritten = _raw("tool-definitions.json")
        generated = _raw("generated-tool-definitions.json")

        definitions = get_mcp_tool_definitions()

        assert set(handwritten) | set(generated) == set(definitions)
        # A hand-written tool, absent if the loader reads only the generated file.
        assert definitions["read-data-schema"].required_scopes
        assert all(definition.title and definition.summary for definition in definitions.values())
