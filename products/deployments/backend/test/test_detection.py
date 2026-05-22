"""Pure-function tests for the framework + package-manager detector."""

from __future__ import annotations

from typing import Any

import pytest

from products.deployments.backend.services.detection import PackageManager, detect_config, detect_package_manager


@pytest.mark.parametrize(
    "lockfiles, expected",
    [
        (["package-lock.json"], PackageManager.NPM),
        (["pnpm-lock.yaml"], PackageManager.PNPM),
        (["yarn.lock"], PackageManager.YARN),
        # Bun pre-1.2 — binary lockfile.
        (["bun.lockb"], PackageManager.BUN),
        # Bun 1.2+ — text lockfile is the new default and must not fall through to npm.
        (["bun.lock"], PackageManager.BUN),
        # Mid-upgrade repo with both Bun lockfiles still resolves to Bun.
        (["bun.lock", "bun.lockb"], PackageManager.BUN),
        # Bun wins over everything — explicit lockfile beats accidental siblings.
        (["bun.lockb", "package-lock.json", "yarn.lock"], PackageManager.BUN),
        (["bun.lock", "package-lock.json", "yarn.lock"], PackageManager.BUN),
        # pnpm beats a leftover npm lockfile from before a migration.
        (["pnpm-lock.yaml", "package-lock.json"], PackageManager.PNPM),
        # Nothing recognisable → npm as the conservative default.
        ([], PackageManager.NPM),
        (["README.md", "Dockerfile"], PackageManager.NPM),
    ],
)
def test_detect_package_manager(lockfiles: list[str], expected: PackageManager) -> None:
    assert detect_package_manager(lockfiles) == expected


@pytest.mark.parametrize(
    "deps, expected_framework, expected_build, expected_output",
    [
        ({"next": "^14"}, "nextjs", "npm run build", "out"),
        ({"vite": "^5"}, "vite", "npm run build", "dist"),
        ({"react-scripts": "5.0.0"}, "create-react-app", "npm run build", "build"),
        ({"astro": "^4"}, "astro", "npm run build", "dist"),
        ({"gatsby": "^5"}, "gatsby", "npm run build", "public"),
        ({"@11ty/eleventy": "^2"}, "eleventy", "npm run build", "_site"),
        ({"@remix-run/react": "^2", "@remix-run/node": "^2"}, "remix", "npm run build", "public"),
        ({"@sveltejs/kit": "^2"}, "sveltekit", "npm run build", "build"),
        ({"nuxt": "^3"}, "nuxt", "npm run generate", ".output/public"),
    ],
)
def test_detect_framework_returns_expected_hint(
    deps: dict[str, str],
    expected_framework: str,
    expected_build: str,
    expected_output: str,
) -> None:
    result = detect_config({"dependencies": deps}, ["package-lock.json"])
    assert result.framework == expected_framework
    assert result.build_command == expected_build
    assert result.output_dir == expected_output


def test_detect_framework_respects_dev_dependencies() -> None:
    # Most projects pin Vite in devDependencies rather than runtime deps.
    result = detect_config({"devDependencies": {"vite": "^5"}}, ["pnpm-lock.yaml"])
    assert result.framework == "vite"
    assert result.build_command == "pnpm build"
    assert result.install_command == "pnpm install --frozen-lockfile"


def test_detect_framework_uses_first_matching_signature() -> None:
    # Remix repos commonly carry React + Vite as transitive concerns; the
    # Remix signature is checked first so it wins over Vite.
    package_json = {"dependencies": {"@remix-run/react": "^2", "@remix-run/node": "^2", "vite": "^5"}}
    result = detect_config(package_json, ["package-lock.json"])
    assert result.framework == "remix"


def test_remix_signature_requires_all_dep_keys_present() -> None:
    # A repo carrying only `@remix-run/react` (as some downstream library's
    # transitive concern) but no Remix runtime is not a Remix project. The
    # signature must require *all* listed deps so we don't suggest a
    # wrong build command that breaks the deploy.
    package_json = {"dependencies": {"@remix-run/react": "^2", "vite": "^5"}}
    result = detect_config(package_json, ["package-lock.json"])
    assert result.framework == "vite"


def test_no_package_json_means_null_framework_with_no_build() -> None:
    # The connect-repo flow should still complete for a static-site repo
    # that's literally just HTML — empty install/build, serve repo root,
    # framework null so the build worker doesn't pretend a framework is in play.
    result = detect_config(None, [])
    assert result.framework is None
    assert result.install_command == ""
    assert result.build_command == ""
    assert result.output_dir == "."


def test_package_json_with_no_known_framework_leaves_build_empty() -> None:
    # Detected the package manager, but nothing we recognise. Install deps
    # but make the user fill in the build command — better than guessing
    # `npm run build` and silently producing the wrong output. Framework
    # stays null so the build worker can have its own go at detection.
    result = detect_config({"dependencies": {"left-pad": "^1.3.0"}}, ["package-lock.json"])
    assert result.framework is None
    assert result.install_command == "npm ci"
    assert result.build_command == ""


@pytest.mark.parametrize(
    "engines, expected",
    [
        ({"node": ">=20"}, "20"),
        ({"node": "^18.17.0"}, "18"),
        ({"node": "22"}, "22"),
        ({"node": "20.x"}, "20"),
        ({}, "20"),
    ],
)
def test_node_version_extracted_from_engines_with_default(
    engines: dict[str, Any],
    expected: str,
) -> None:
    package_json = {"engines": engines, "dependencies": {"vite": "^5"}}
    result = detect_config(package_json, ["package-lock.json"])
    assert result.node_version == expected


def test_install_command_matches_package_manager() -> None:
    for manager, lockfile, expected_install in [
        (PackageManager.NPM, "package-lock.json", "npm ci"),
        (PackageManager.PNPM, "pnpm-lock.yaml", "pnpm install --frozen-lockfile"),
        (PackageManager.YARN, "yarn.lock", "yarn install --frozen-lockfile"),
        (PackageManager.BUN, "bun.lockb", "bun install --frozen-lockfile"),
    ]:
        result = detect_config({"dependencies": {"vite": "^5"}}, [lockfile])
        assert result.package_manager == manager
        assert result.install_command == expected_install
