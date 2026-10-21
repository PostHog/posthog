#!/usr/bin/env python3
"""Print the Rust images a pull request must build because it changes how images build.

Cargo CI never runs the Docker build, so a change to a Dockerfile, the build context,
or an image entry can pass on the pull request and fail only on master, where it
blocks the deploy. One image per Dockerfile and target covers a build-recipe change,
and an added or edited image entry covers itself. Output is a comma-separated image
filter for _rust-build-images.yml, or an empty line when nothing needs a build.

Usage: select_rust_image_checks.py <base-ref>  (run from the repo root)
"""

import sys
import subprocess
from pathlib import Path
from typing import Any

import yaml

IMAGES_FILE = ".github/rust-images.yml"
SHARED_INPUTS = ("rust/.dockerignore", "rust/.cargo/", ".github/workflows/_rust-build-images.yml")


def select_images(
    changed_files: list[str], base_images: list[dict[str, Any]], head_images: list[dict[str, Any]]
) -> list[str]:
    representatives: dict[tuple[str, str], str] = {}
    for entry in head_images:
        dockerfile = entry["dockerfile"].removeprefix("./")
        representatives.setdefault((dockerfile, entry.get("target", "")), entry["image"])

    shared_changed = any(f.startswith(SHARED_INPUTS) for f in changed_files)
    selected = {
        image for (dockerfile, _), image in representatives.items() if shared_changed or dockerfile in changed_files
    }
    if IMAGES_FILE in changed_files:
        selected.update(entry["image"] for entry in head_images if entry not in base_images)
    return sorted(selected)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def main(base_ref: str) -> None:
    changed_files = git("diff", "--name-only", base_ref, "HEAD").splitlines()
    base_images = yaml.safe_load(git("show", f"{base_ref}:{IMAGES_FILE}"))
    head_images = yaml.safe_load(Path(IMAGES_FILE).read_text())
    sys.stdout.write(",".join(select_images(changed_files, base_images, head_images)) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
