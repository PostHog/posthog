import json
import subprocess
from pathlib import Path

import yaml
from hogli_commands.change_detection import matches_globs
from hogli_commands.projections import OXFMT, PROJECTIONS, formatter_for

REPO_ROOT = Path(__file__).resolve().parents[3]

# Directories a code generation pipeline owns in full: drf-spectacular and Orval output,
# schema codegen, and the MCP tool and UI-app pipelines. `*` spans `/` in fnmatch.
PIPELINE_ROOTS = (
    "frontend/src/generated/*",
    "products/*/frontend/generated/*",
    "nodejs/src/common/generated/*",
    "posthog/usage_ingestion/generated/*",
    "services/mcp/src/generated/*",
    "services/mcp/src/tools/generated/*",
    "services/mcp/src/ui-apps/generated/*",
    "services/mcp/src/ui-apps/apps/generated/*",
)

# Generated files that a Node or Rust pipeline writes, with that producer. A Python
# projection never goes here: it is an entry in PROJECTIONS.
EXTERNAL_PRODUCERS = {
    "frontend/src/lib/agentScopes.generated.ts": "services/mcp/scripts/build-cli-agent-scopes.ts",
    "services/mcp/src/resources/ui-apps.generated.ts": "services/mcp/scripts/generate-ui-apps.ts",
    "rust/common/ingestion_warnings/warning_types.generated.json": (
        "nodejs/src/ingestion/common/scripts/generate-ingestion-warning-types.ts"
    ),
}

HOW_TO_FIX = (
    "A generated file needs a known producer, so no side generator grows next to the OpenAPI flow.\n"
    "- The frontend or the MCP server needs the values an API accepts or returns: type the serializer\n"
    "  field and use the generated *EnumApi from `hogli build:openapi`.\n"
    "- The data is rows no endpoint serves: add a renderer and an entry to PROJECTIONS in\n"
    "  tools/hogli-commands/hogli_commands/projections.py, then run `hogli build:projections`.\n"
    "See docs/published/handbook/engineering/type-system.md, 'Side generators'."
)


def _tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True)
    return [path for path in result.stdout.decode().split("\0") if path]


def _looks_generated(path: str) -> bool:
    return ".generated." in Path(path).name or "/generated/" in f"/{path}"


def test_every_generated_file_has_a_known_producer() -> None:
    registered = {output for projection in PROJECTIONS for output in projection.outputs}
    unknown = [
        path
        for path in _tracked_files()
        if _looks_generated(path)
        and path not in registered
        and path not in EXTERNAL_PRODUCERS
        and not matches_globs(path, PIPELINE_ROOTS)
    ]

    assert unknown == [], f"Generated files with no known producer: {unknown}\n{HOW_TO_FIX}"


def test_the_registry_matches_the_tree() -> None:
    outputs = [output for projection in PROJECTIONS for output in projection.outputs]
    known = set(outputs) | set(EXTERNAL_PRODUCERS)

    assert [p.renderer for p in PROJECTIONS if not (REPO_ROOT / p.renderer).is_file()] == []
    assert [path for path in known if not (REPO_ROOT / path).is_file()] == []
    assert sorted(output for output in set(outputs) if outputs.count(output) > 1) == []
    assert sorted(set(outputs) & set(EXTERNAL_PRODUCERS)) == []


def _ci_python_filter(name: str) -> list[str]:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci-python.yml").read_text())
    [step] = [step for step in workflow["jobs"]["changes"]["steps"] if step.get("id") == "filter"]
    return yaml.safe_load(step["with"]["filters"])[name]


def test_every_output_reaches_the_drift_check() -> None:
    python_filter = _ci_python_filter("python")
    missing = [
        output
        for projection in PROJECTIONS
        for output in projection.outputs
        if not matches_globs(output, python_filter)
    ]

    assert missing == [], (
        f"Projection outputs missing from the `python` paths filter in ci-python.yml: {missing}. "
        "Add them, so a hand-edit still runs `hogli build:projections --check`."
    )


def test_oxfmt_ignores_no_projection_output() -> None:
    ignored = json.loads((REPO_ROOT / OXFMT.config).read_text())["ignorePatterns"]
    skipped = [
        output
        for projection in PROJECTIONS
        for output in projection.outputs
        if formatter_for(output) == OXFMT and matches_globs(output, ignored)
    ]

    assert skipped == [], (
        f"{OXFMT.config} ignores projection outputs: {skipped}. oxfmt returns an ignored file "
        "unchanged, so the output would skip house style without an error. Remove the pattern."
    )
