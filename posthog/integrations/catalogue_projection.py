"""Render `catalogue_generated.json` from the provider registry of the credentials service.

A renderer in the projection registry (`tools/hogli-commands/hogli_commands/projections.py`). Run
`hogli build:projections --only credentials-catalogue` after a change under
`services/credentials-service/src/providers/`.

The TypeScript registry is the source of truth. This bundles its `src/catalogue.ts` entry with
esbuild and runs it with node. The CI job that checks projections has node and npm but no
node_modules, so the entry imports no npm package, and esbuild comes from npm at the locked version
when the service's own copy is not installed.
"""

import json
import tempfile
import subprocess
from pathlib import Path

import yaml

OUTPUT = "posthog/integrations/catalogue_generated.json"

SERVICE = "services/credentials-service"
ENTRY = "src/catalogue.ts"

REPO_ROOT = Path(__file__).resolve().parents[2]


def _locked_esbuild_version() -> str:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    lock = yaml.load((REPO_ROOT / "pnpm-lock.yaml").read_text(), Loader=loader)
    return str(lock["importers"][SERVICE]["devDependencies"]["esbuild"]["version"])


def _esbuild_command(npm_prefix: str) -> list[str]:
    version = _locked_esbuild_version()
    installed = REPO_ROOT / SERVICE / "node_modules" / "esbuild"
    if (installed / "package.json").exists() and json.loads((installed / "package.json").read_text())[
        "version"
    ] == version:
        return [str(REPO_ROOT / SERVICE / "node_modules" / ".bin" / "esbuild")]
    # An empty prefix, so npm does not read the repo's package.json and take esbuild as installed.
    return [
        "npm",
        "exec",
        "--yes",
        "--prefer-offline",
        f"--prefix={npm_prefix}",
        f"--package=esbuild@{version}",
        "--",
        "esbuild",
    ]


def _run(command: list[str], *, stdin: str | None = None) -> str:
    result = subprocess.run(
        command,
        input=stdin,
        cwd=REPO_ROOT / SERVICE,
        capture_output=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command[:3])} failed:\n{result.stderr or result.stdout}")
    return result.stdout


def render_catalogue() -> str:
    with tempfile.TemporaryDirectory() as npm_prefix:
        bundle = _run(
            [*_esbuild_command(npm_prefix), ENTRY, "--bundle", "--platform=node", "--format=esm", "--log-level=warning"]
        )
    # Parsed and dumped again, so the bytes do not depend on how the entry spaces its JSON.
    catalogue = json.loads(_run(["node", "--input-type=module"], stdin=bundle))
    return json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n"


def render() -> dict[str, str]:
    return {OUTPUT: render_catalogue()}
