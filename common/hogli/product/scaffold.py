"""Product bootstrapping — scaffold new products and register them in config files."""

from __future__ import annotations

import re
import json
from collections.abc import Callable
from pathlib import Path

import click

from .paths import DJANGO_SETTINGS, FRONTEND_PACKAGE_JSON, PRODUCTS_DIR, TACH_TOML, load_structure


def flatten_structure(files: dict, prefix: str = "", result: dict | None = None) -> dict[str, dict]:
    """
    Flatten nested structure dict into flat paths.
    e.g., {"facade/": {"api.py": {...}}} -> {"facade/api.py": {...}}
    """
    if result is None:
        result = {}
    for name, config in files.items():
        if name.endswith("/"):
            flatten_structure(config, prefix + name, result)
        else:
            result[prefix + name] = config if isinstance(config, dict) else {}
    return result


def _render_template(template: str, product_name: str) -> str:
    pascal_name = "".join(word.capitalize() for word in product_name.split("_"))
    return template.format(product=product_name, Product=pascal_name)


def _register_in_file(
    file_path: Path, label: str, needle: str, write_fn: Callable[[str], str | None], *, dry_run: bool
) -> None:
    """Register a product entry in a config file. Skips if needle already present."""
    if not file_path.exists():
        return
    content = file_path.read_text()
    if needle in content:
        click.echo(f"\n  Already in {label}: {needle}")
        return
    if dry_run:
        click.echo(f"\n  Would add to {label}: {needle}")
        return
    result = write_fn(content)
    if result is not None:
        file_path.write_text(result)
        click.echo(f"\n  Added to {label}: {needle}")


def _add_to_tach_toml(product_name: str, *, dry_run: bool) -> None:
    module_path = f"products.{product_name}"
    block = (
        f"\n[[modules]]\n"
        f'path = "{module_path}"\n'
        f'depends_on = ["posthog"]\n'
        f'layer = "products"\n'
        f"interfaces = [\n"
        f'    "{module_path}.backend.facade",\n'
        f'    "{module_path}.backend.presentation.views",\n'
        f"]\n"
    )
    _register_in_file(
        TACH_TOML,
        "tach.toml",
        f'path = "{module_path}"',
        lambda content: content.rstrip() + "\n" + block,
        dry_run=dry_run,
    )


def _add_to_frontend_package_json(product_name: str, *, dry_run: bool) -> None:
    pkg_name = f"@posthog/products-{product_name.replace('_', '-')}"

    def write(content: str) -> str:
        data = json.loads(content)
        deps = data.get("dependencies", {})
        deps[pkg_name] = "workspace:*"
        data["dependencies"] = dict(sorted(deps.items()))
        return json.dumps(data, indent=4) + "\n"

    _register_in_file(FRONTEND_PACKAGE_JSON, "frontend/package.json", pkg_name, write, dry_run=dry_run)


def _add_to_django_settings(product_name: str, *, dry_run: bool) -> None:
    pascal_name = "".join(word.capitalize() for word in product_name.split("_"))
    app_config = f"products.{product_name}.backend.apps.{pascal_name}Config"

    def write(content: str) -> str | None:
        pattern = r'(    "products\.[^"]+",\n)(?!    "products\.)'
        match = list(re.finditer(pattern, content))
        if not match:
            click.echo(f"\n  Could not find INSTALLED_APPS products section — add manually: {app_config}")
            return None
        insert_pos = match[-1].end()
        return content[:insert_pos] + f'    "{app_config}",\n' + content[insert_pos:]

    _register_in_file(DJANGO_SETTINGS, "Django settings", app_config, write, dry_run=dry_run)


_VALID_PRODUCT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def bootstrap_product(name: str, dry_run: bool, force: bool) -> None:
    if not _VALID_PRODUCT_NAME_RE.match(name):
        raise click.ClickException(
            f"Invalid product name '{name}' — must be lowercase, start with a letter, and contain only [a-z0-9_]."
        )
    product_dir = PRODUCTS_DIR / name

    if product_dir.exists() and not force:
        raise click.ClickException(f"Product '{name}' already exists at {product_dir}. Use --force to overwrite.")

    structure = load_structure()
    created: list[str] = []
    skipped: list[str] = []

    for path, config in flatten_structure(structure.get("root_files", {})).items():
        file_path = product_dir / path
        if dry_run:
            (skipped if (file_path.exists() and not force) else created).append(path)
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists() and not force:
            skipped.append(path)
            continue
        file_path.write_text(_render_template(config.get("template", ""), name))
        created.append(path)

    for path, config in flatten_structure(structure.get("backend_files", {})).items():
        file_path = product_dir / "backend" / path
        label = f"backend/{path}"
        if dry_run:
            (skipped if (file_path.exists() and not force) else created).append(label)
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists() and not force:
            skipped.append(label)
            continue
        file_path.write_text(_render_template(config.get("template", ""), name))
        created.append(label)

    for folder_name in structure.get("frontend_files", {}).keys():
        folder_path = product_dir / "frontend" / folder_name.rstrip("/")
        label = f"frontend/{folder_name}"
        if dry_run:
            created.append(label)
        else:
            folder_path.mkdir(parents=True, exist_ok=True)
            created.append(label)

    click.echo(f"{'Would create' if dry_run else 'Created'} product '{name}' at {product_dir}")
    if created:
        click.echo(f"\n  Created {len(created)} files/folders:")
        for path in created:
            click.echo(f"    {path}")
    if skipped:
        click.echo(f"\n  Skipped {len(skipped)} existing files:")
        for path in skipped:
            click.echo(f"    {path}")

    _add_to_tach_toml(name, dry_run=dry_run)
    _add_to_frontend_package_json(name, dry_run=dry_run)
    _add_to_django_settings(name, dry_run=dry_run)
