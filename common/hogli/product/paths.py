"""Shared path constants and structure loader."""

from pathlib import Path

import yaml

# product/ -> hogli/ -> common/ -> repo root
REPO_ROOT = Path(__file__).parent.parent.parent.parent
STRUCTURE_FILE = Path(__file__).parent.parent / "product_structure.yaml"
PRODUCTS_DIR = REPO_ROOT / "products"
TACH_TOML = REPO_ROOT / "tach.toml"
FRONTEND_PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
DJANGO_SETTINGS = REPO_ROOT / "posthog" / "settings" / "web.py"
DB_ROUTING_YAML = PRODUCTS_DIR / "db_routing.yaml"


def load_structure() -> dict:
    return yaml.safe_load(STRUCTURE_FILE.read_text())
