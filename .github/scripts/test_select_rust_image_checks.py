import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("select_rust_image_checks.py")
SPEC = importlib.util.spec_from_file_location("select_rust_image_checks", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
selection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection)

IMAGES = [
    {"image": "capture", "dockerfile": "./rust/Dockerfile"},
    {"image": "sqlx-migrate", "dockerfile": "./rust/Dockerfile.sqlx-migrate"},
    {"image": "cymbal", "dockerfile": "./rust/Dockerfile"},
    {"image": "flags-cache-warmer", "dockerfile": "./rust/Dockerfile", "target": "runtime-jumphost"},
]
ADDED = {"image": "new-service", "dockerfile": "./rust/Dockerfile"}
EDITED_CYMBAL = {"image": "cymbal", "dockerfile": "./rust/Dockerfile", "features": "profiling"}


@pytest.mark.parametrize(
    "changed_files,head_images,expected",
    [
        (["rust/capture/src/main.rs", "rust/Cargo.lock"], IMAGES, []),
        ([".github/workflows/rust-smoke-test-build.yml"], IMAGES, []),
        (["rust/Dockerfile"], IMAGES, ["capture", "flags-cache-warmer"]),
        (["rust/Dockerfile.sqlx-migrate"], IMAGES, ["sqlx-migrate"]),
        (["rust/.dockerignore"], IMAGES, ["capture", "flags-cache-warmer", "sqlx-migrate"]),
        (["rust/.cargo/config.toml"], IMAGES, ["capture", "flags-cache-warmer", "sqlx-migrate"]),
        ([".github/workflows/_rust-build-images.yml"], IMAGES, ["capture", "flags-cache-warmer", "sqlx-migrate"]),
        ([".github/rust-images.yml"], IMAGES, []),
        ([".github/rust-images.yml"], [*IMAGES, ADDED], ["new-service"]),
        ([".github/rust-images.yml"], [IMAGES[0], IMAGES[1], EDITED_CYMBAL, IMAGES[3]], ["cymbal"]),
        (
            [".github/rust-images.yml", "rust/Dockerfile.sqlx-migrate"],
            [*IMAGES, ADDED],
            ["new-service", "sqlx-migrate"],
        ),
    ],
)
def test_select_images(changed_files: list[str], head_images: list[dict[str, str]], expected: list[str]) -> None:
    assert selection.select_images(changed_files, IMAGES, head_images) == expected
