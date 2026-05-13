#!/usr/bin/env python3
"""Best-effort changed-file to route mapper for qa-runtime."""

from __future__ import annotations

import re
import sys
import json
import argparse
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class RouteMatch:
    file: str
    route: str
    source: str
    scene: str | None
    reason: str


def read_json_file(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return [str(item) for item in data]
    if isinstance(data, dict) and isinstance(data.get("files"), list):
        return [str(item) for item in data["files"]]
    raise SystemExit("files JSON must be a list or an object with a files list")


def normalize_import(base: Path, import_path: str) -> str:
    if import_path.startswith("."):
        resolved = (base.parent / import_path).resolve()
        try:
            relative = resolved.relative_to(ROOT)
        except ValueError:
            return import_path
        return relative.as_posix()
    if import_path.startswith("scenes/"):
        return f"frontend/src/{import_path}"
    if import_path.startswith("products/"):
        return import_path
    return import_path


def extract_core_scene_imports() -> dict[str, str]:
    app_scenes = ROOT / "frontend/src/scenes/appScenes.ts"
    if not app_scenes.exists():
        return {}
    text = app_scenes.read_text()
    imports: dict[str, str] = {}
    pattern = re.compile(r"\[Scene\.([A-Za-z0-9_]+)\]\s*:\s*\(\)\s*=>\s*import\(['\"]([^'\"]+)['\"]\)")
    for scene, import_path in pattern.findall(text):
        imports[scene] = normalize_import(app_scenes, import_path)
    return imports


def extract_core_routes() -> dict[str, list[str]]:
    scenes = ROOT / "frontend/src/scenes/scenes.ts"
    if not scenes.exists():
        return {}
    text = scenes.read_text()
    routes: dict[str, list[str]] = {}
    pattern = re.compile(r"\[(urls\.[^\]]+)\]\s*:\s*\[Scene\.([A-Za-z0-9_]+),\s*['\"]([^'\"]+)['\"]\]")
    for route_expr, scene, scene_key in pattern.findall(text):
        routes.setdefault(scene, []).append(f"{route_expr} [{scene_key}]")
    literal_pattern = re.compile(r"['\"]([^'\"]+)['\"]\s*:\s*\[Scene\.([A-Za-z0-9_]+),\s*['\"]([^'\"]+)['\"]\]")
    for route, scene, scene_key in literal_pattern.findall(text):
        routes.setdefault(scene, []).append(f"{route} [{scene_key}]")
    return routes


def extract_product_scene_imports(manifest: Path) -> dict[str, str]:
    text = manifest.read_text()
    scenes: dict[str, str] = {}
    scene_pattern = re.compile(
        r"^\s*([A-Za-z0-9_]+)\s*:\s*\{(?P<body>.*?^\s*\},?)",
        re.MULTILINE | re.DOTALL,
    )
    for match in scene_pattern.finditer(text):
        scene = match.group(1)
        body = match.group("body")
        import_match = re.search(r"import\s*:\s*\(\)\s*=>\s*import\(['\"]([^'\"]+)['\"]\)", body)
        if import_match:
            scenes[scene] = normalize_import(manifest, import_match.group(1))
    return scenes


def extract_product_routes(manifest: Path) -> dict[str, list[str]]:
    text = manifest.read_text()
    routes_block = re.search(r"routes\s*:\s*\{(?P<body>.*?)^\s*\},", text, re.MULTILINE | re.DOTALL)
    if not routes_block:
        return {}
    routes: dict[str, list[str]] = {}
    route_pattern = re.compile(r"['\"]([^'\"]+)['\"]\s*:\s*\[\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]")
    for route, scene, scene_key in route_pattern.findall(routes_block.group("body")):
        routes.setdefault(scene, []).append(f"{route} [{scene_key}]")
    return routes


def path_matches_import(changed_file: str, imported_path: str, *, allow_parent_match: bool) -> bool:
    changed = changed_file.removesuffix(".tsx").removesuffix(".ts").removesuffix(".jsx").removesuffix(".js")
    imported = imported_path.removesuffix(".tsx").removesuffix(".ts").removesuffix(".jsx").removesuffix(".js")
    imported_parent = str(Path(imported).parent)
    changed_parent = str(Path(changed).parent)
    direct_match = changed == imported or changed.startswith(f"{imported}/") or imported.startswith(f"{changed}/")
    parent_match = changed_parent == imported_parent or changed.startswith(f"{imported_parent}/")
    return direct_match or (allow_parent_match and parent_match)


def core_matches(changed_file: str) -> list[RouteMatch]:
    imports = extract_core_scene_imports()
    routes = extract_core_routes()
    matches: list[RouteMatch] = []
    for scene, imported_path in imports.items():
        if path_matches_import(changed_file, imported_path, allow_parent_match=True):
            for route in routes.get(scene, []):
                matches.append(
                    RouteMatch(
                        file=changed_file,
                        route=route,
                        source="frontend/src/scenes",
                        scene=scene,
                        reason=f"changed file matches Scene.{scene} import {imported_path}",
                    )
                )
    return matches


def product_matches(changed_file: str) -> list[RouteMatch]:
    parts = Path(changed_file).parts
    if len(parts) < 2 or parts[0] != "products":
        return []
    manifest = ROOT / "products" / parts[1] / "manifest.tsx"
    if not manifest.exists():
        return []
    imports = extract_product_scene_imports(manifest)
    routes = extract_product_routes(manifest)
    matches: list[RouteMatch] = []
    if changed_file == manifest.relative_to(ROOT).as_posix():
        for scene, scene_routes in routes.items():
            for route in scene_routes:
                matches.append(
                    RouteMatch(
                        file=changed_file,
                        route=route,
                        source=manifest.relative_to(ROOT).as_posix(),
                        scene=scene,
                        reason="manifest changed; route belongs to changed product",
                    )
                )
        return matches
    for scene, imported_path in imports.items():
        if path_matches_import(changed_file, imported_path, allow_parent_match=False):
            for route in routes.get(scene, []):
                matches.append(
                    RouteMatch(
                        file=changed_file,
                        route=route,
                        source=manifest.relative_to(ROOT).as_posix(),
                        scene=scene,
                        reason=f"changed file matches product scene {scene} import {imported_path}",
                    )
                )
    return matches


def fallback_url_hints(changed_file: str) -> list[RouteMatch]:
    path = ROOT / changed_file
    if not path.exists() or path.suffix not in {".ts", ".tsx"}:
        return []
    text = path.read_text(errors="ignore")
    routes = sorted(set(re.findall(r"`(/[^`$]+)`|['\"](/[^'\"{}$]+)['\"]", text)))
    flattened = [item for group in routes for item in group if item]
    return [
        RouteMatch(
            file=changed_file,
            route=route,
            source=changed_file,
            scene=None,
            reason="literal URL found in changed file",
        )
        for route in flattened
    ]


def walk(files: list[str]) -> dict[str, object]:
    all_matches: list[RouteMatch] = []
    gaps: list[dict[str, str]] = []
    for changed_file in files:
        matches = core_matches(changed_file) + product_matches(changed_file) + fallback_url_hints(changed_file)
        if matches:
            all_matches.extend(matches)
        elif changed_file.startswith(("frontend/src/", "products/")) and Path(changed_file).suffix in {".ts", ".tsx"}:
            gaps.append({"file": changed_file, "reason": "no route mapping found"})

    unique: dict[tuple[str, str], RouteMatch] = {}
    for match in all_matches:
        unique[(match.file, match.route)] = match

    return {
        "routes": [
            {
                "file": match.file,
                "route": match.route,
                "source": match.source,
                "scene": match.scene,
                "reason": match.reason,
            }
            for match in sorted(unique.values(), key=lambda item: (item.file, item.route))
        ],
        "coverage_gaps": gaps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Map changed frontend files to likely PostHog routes.")
    parser.add_argument("--files-json", type=Path, required=True, help="JSON list of changed file paths")
    args = parser.parse_args()
    sys.stdout.write(f"{json.dumps(walk(read_json_file(args.files_json)), indent=2, sort_keys=True)}\n")


if __name__ == "__main__":
    main()
