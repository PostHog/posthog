"""Framework + package-manager detection for connected repositories.

Pure inspection — no I/O, no DB. The caller fetches `package.json` and the
list of present lockfiles from the repo root (via GitHub raw content, a
temporary clone, or wherever) and hands them in; we return a suggested
build configuration the UI can prefill.

The detection table is the only place where framework signatures live;
new frameworks land here as one entry rather than scattered specials in
the build worker. Framework names match the free-text convention on
`DeploymentProject.framework` (lowercase, no spaces, e.g. `nextjs`,
`vite`, `astro`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PackageManager(StrEnum):
    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    BUN = "bun"


@dataclass(frozen=True)
class DetectedConfig:
    """Suggested config from a repo's `package.json` + lockfile presence.

    `framework` is `None` when no signature matched — the UI should leave
    `DeploymentProject.framework` null so the build worker falls back to
    its own auto-detection. `install_command` and `node_version` are
    informational; `DeploymentProject` doesn't store them today.
    """

    package_manager: PackageManager
    install_command: str
    build_command: str
    output_dir: str
    node_version: str
    framework: str | None


# (lockfile_name, package_manager) — order matters: if a repo has both a
# pnpm lockfile and a leftover `package-lock.json`, pnpm wins because the
# pnpm lockfile is the explicit signal a developer is using pnpm. npm is
# the last-resort default because `package-lock.json` is what npm happily
# generates on top of anything.
#
# Bun has two lockfile names in the wild: `bun.lockb` (binary, pre-1.2) and
# `bun.lock` (text, 1.2+ default). Both are listed so a fresh Bun 1.2 repo
# doesn't fall through to npm.
_LOCKFILE_PRECEDENCE: tuple[tuple[str, PackageManager], ...] = (
    ("bun.lock", PackageManager.BUN),
    ("bun.lockb", PackageManager.BUN),
    ("pnpm-lock.yaml", PackageManager.PNPM),
    ("yarn.lock", PackageManager.YARN),
    ("package-lock.json", PackageManager.NPM),
)


def detect_package_manager(lockfile_names: list[str]) -> PackageManager:
    """Pick a package manager from the lockfiles present in the repo root."""
    present = set(lockfile_names)
    for lockfile, manager in _LOCKFILE_PRECEDENCE:
        if lockfile in present:
            return manager
    return PackageManager.NPM


def _install_command_for(manager: PackageManager) -> str:
    return {
        PackageManager.NPM: "npm ci",
        PackageManager.PNPM: "pnpm install --frozen-lockfile",
        PackageManager.YARN: "yarn install --frozen-lockfile",
        PackageManager.BUN: "bun install --frozen-lockfile",
    }[manager]


def _build_invocation(manager: PackageManager, script: str) -> str:
    """`<manager> run <script>` for all four — `npm run build`, `pnpm build`, etc."""
    prefix = {
        PackageManager.NPM: "npm run",
        PackageManager.PNPM: "pnpm",
        PackageManager.YARN: "yarn",
        PackageManager.BUN: "bun run",
    }[manager]
    return f"{prefix} {script}"


@dataclass(frozen=True)
class _FrameworkSignature:
    """Detection rule for one framework.

    `dep_keys` is the set of dependencies that must *all* be present in the
    union of `dependencies` + `devDependencies` for this framework to match.
    First signature whose deps all match wins, so order in
    `_FRAMEWORK_SIGNATURES` is significant — more specific frameworks
    (Remix, SvelteKit, Nuxt) come before more general ones that share a
    transitive dep (Vite, React).

    `all()` (not `any()`): a repo carrying only `@remix-run/react` without
    `@remix-run/node` is some downstream package's transitive dep, not a
    Remix project. Picking Remix here would suggest the wrong build
    command and break the user's deploy.
    """

    framework: str
    dep_keys: tuple[str, ...]
    build_script: str
    output_dir: str


_FRAMEWORK_SIGNATURES: tuple[_FrameworkSignature, ...] = (
    _FrameworkSignature("nextjs", ("next",), "build", "out"),
    _FrameworkSignature("remix", ("@remix-run/react", "@remix-run/node"), "build", "public"),
    _FrameworkSignature("sveltekit", ("@sveltejs/kit",), "build", "build"),
    _FrameworkSignature("nuxt", ("nuxt",), "generate", ".output/public"),
    _FrameworkSignature("astro", ("astro",), "build", "dist"),
    _FrameworkSignature("gatsby", ("gatsby",), "build", "public"),
    _FrameworkSignature("eleventy", ("@11ty/eleventy",), "build", "_site"),
    _FrameworkSignature("vite", ("vite",), "build", "dist"),
    _FrameworkSignature("create-react-app", ("react-scripts",), "build", "build"),
)


def _collect_dependency_keys(package_json: dict[str, Any]) -> set[str]:
    deps = package_json.get("dependencies") or {}
    dev_deps = package_json.get("devDependencies") or {}
    if not isinstance(deps, dict) or not isinstance(dev_deps, dict):
        return set()
    return set(deps.keys()) | set(dev_deps.keys())


def _detect_framework_signature(package_json: dict[str, Any]) -> _FrameworkSignature | None:
    all_deps = _collect_dependency_keys(package_json)
    for signature in _FRAMEWORK_SIGNATURES:
        if all(dep in all_deps for dep in signature.dep_keys):
            return signature
    return None


def _detect_node_version(package_json: dict[str, Any]) -> str:
    """Extract a Node major version from `engines.node`, falling back to "20".

    `engines.node` is a semver range. We don't need to evaluate the range —
    just pull the leading major number so we know which Node line to
    install. "Doesn't pick the freshest patch" is fine; the build env can
    decide that.
    """
    engines = package_json.get("engines") or {}
    if not isinstance(engines, dict):
        return "20"
    node_constraint = engines.get("node")
    if not isinstance(node_constraint, str):
        return "20"
    for char in node_constraint:
        if char.isdigit():
            return _read_leading_int(node_constraint[node_constraint.index(char) :])
    return "20"


def _read_leading_int(s: str) -> str:
    digits: list[str] = []
    for char in s:
        if char.isdigit():
            digits.append(char)
        else:
            break
    return "".join(digits) or "20"


def detect_config(
    package_json: dict[str, Any] | None,
    lockfile_names: list[str],
) -> DetectedConfig:
    """Suggest a config from a repo's `package.json` + lockfile presence.

    `package_json=None` (or an empty dict) means "no package.json found" —
    treated as a plain-HTML repo: no install, no build, serve the root.

    The returned config is a suggestion; the user can override every field
    in the connect-repo UI. Detection should never raise — bad inputs land
    on the plain-HTML fallback so the connect flow can still complete and
    the user fixes things in the form.
    """
    manager = detect_package_manager(lockfile_names)

    if not package_json:
        return DetectedConfig(
            package_manager=manager,
            install_command="",
            build_command="",
            output_dir=".",
            node_version="20",
            framework=None,
        )

    signature = _detect_framework_signature(package_json)
    node_version = _detect_node_version(package_json)

    if signature is None:
        # `package.json` present but no known framework — leave the build
        # command empty so the user has to fill it in. We return
        # `framework=None` so the build worker's own auto-detection can
        # have a go.
        return DetectedConfig(
            package_manager=manager,
            install_command=_install_command_for(manager),
            build_command="",
            output_dir="dist",
            node_version=node_version,
            framework=None,
        )

    return DetectedConfig(
        package_manager=manager,
        install_command=_install_command_for(manager),
        build_command=_build_invocation(manager, signature.build_script),
        output_dir=signature.output_dir,
        node_version=node_version,
        framework=signature.framework,
    )
