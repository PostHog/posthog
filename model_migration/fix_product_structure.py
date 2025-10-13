#!/usr/bin/env python3
"""
Quick script to fix product folder structure.
Moves Python packages from products/{app}/ to products/{app}/backend/
Updates Django settings to use proper AppConfig paths.
"""

import re
import shutil
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")


def main():
    root_dir = Path.cwd()
    products_dir = root_dir / "products"

    if not products_dir.exists():
        logging.error(f"❌ Products directory not found: {products_dir}")
        return

    logging.info(f"🔍 Scanning {products_dir} for incorrect structure...")

    fixes_needed = []

    # Check each product directory
    for product_path in products_dir.iterdir():
        if not product_path.is_dir() or product_path.name.startswith("__"):
            continue

        product_name = product_path.name

        # Check current state of product structure
        backend_dir = product_path / "backend"
        init_py_root = product_path / "__init__.py"
        init_py_backend = backend_dir / "__init__.py" if backend_dir.exists() else None

        # Determine if this product needs fixing (with error handling)
        try:
            has_python_in_root = init_py_root.exists() or any(
                f.suffix == ".py" for f in product_path.iterdir() if f.is_file()
            )
            has_correct_backend = backend_dir.exists() and init_py_backend and init_py_backend.exists()
        except (PermissionError, OSError) as e:
            logging.warning(f"⚠️  Could not scan {product_name}: {e}")
            continue

        if has_python_in_root and not has_correct_backend:
            # Python files in root, needs fixing
            fixes_needed.append(product_name)
            logging.warning(f"❌ {product_name} has Python package directly in product folder")
        elif has_python_in_root and has_correct_backend:
            # Has both root and backend Python files (partial migration?)
            fixes_needed.append(product_name)
            logging.warning(f"❌ {product_name} has Python files in both root and backend (needs cleanup)")
        elif has_correct_backend:
            # Correct backend structure
            logging.info(f"✅ {product_name} has correct backend structure")
        else:
            # No Python files found (frontend-only or empty)
            logging.info(f"⚠️  {product_name} has no Python package (might be frontend-only)")

    # Ensure products/__init__.py exists (needed for pytest discovery)
    products_init = products_dir / "__init__.py"
    if not products_init.exists():
        try:
            products_init.touch()
            logging.info("📝 Created products/__init__.py (needed for pytest)")
        except (PermissionError, OSError) as e:
            logging.warning(f"⚠️  Failed to create products/__init__.py: {e}")

    if not fixes_needed:
        logging.info("\n✅ All product folders follow correct structure!")

        # Check if Django settings need updating even if no structure fixes are needed
        logging.info("\n🔧 Checking Django settings...")
        products_with_backend = []
        for product_path in products_dir.iterdir():
            if not product_path.is_dir() or product_path.name.startswith("__"):
                continue

            backend_dir = product_path / "backend"
            if backend_dir.exists() and (backend_dir / "__init__.py").exists():
                products_with_backend.append(product_path.name)

        if products_with_backend:
            update_django_settings(root_dir, products_with_backend)

        return

    logging.info(f"\n🔧 Found {len(fixes_needed)} products to fix:")
    for product in fixes_needed:
        logging.info(f"  - {product}")

    logging.info("\n🔧 Applying fixes (idempotent operations)...")

    # Apply fixes
    for product_name in fixes_needed:
        fix_product_structure(products_dir / product_name, product_name)

    if fixes_needed:
        logging.info("\n🔧 Updating Django settings...")
        update_django_settings(root_dir, fixes_needed)

    logging.info("\n✅ All fixes applied!")


def fix_product_structure(product_path: Path, product_name: str):
    """Move Python package from product root to product/backend/ (idempotent)"""
    logging.info(f"\n🔧 Fixing {product_name}...")

    backend_dir = product_path / "backend"

    # Create backend directory (idempotent)
    backend_dir.mkdir(exist_ok=True)
    if not backend_dir.exists():
        logging.info(f"  📁 Created {backend_dir}")

    # Find Python files to move (only from product root, not subdirs)
    python_files_to_move = []
    for item in product_path.iterdir():
        # Skip if it's a directory (including backend dir)
        if item.is_dir():
            continue
        # Only move .py files from product root
        if item.is_file() and item.suffix == ".py":
            dest_path = backend_dir / item.name
            # Only move if destination doesn't exist (idempotent)
            if not dest_path.exists():
                python_files_to_move.append(item)
            else:
                logging.info(f"  ℹ️  {item.name} already exists in backend/, skipping")

    if not python_files_to_move:
        # Check if there are already Python files in backend
        backend_py_files = list(backend_dir.glob("*.py")) if backend_dir.exists() else []
        if backend_py_files:
            logging.info(f"  ℹ️  Python files already in correct location in backend/")
        else:
            logging.warning(f"  ⚠️  No Python files found to move for {product_name}")
    else:
        # Move Python files to backend/ (idempotent with error handling)
        for py_file in python_files_to_move:
            dest = backend_dir / py_file.name
            try:
                logging.info(f"  📦 Moving {py_file.name} → backend/{py_file.name}")
                shutil.move(str(py_file), str(dest))
            except (PermissionError, OSError, shutil.Error) as e:
                logging.exception(f"  ❌ Failed to move {py_file.name}: {e}")
                continue

    # Move migrations directory to backend if it exists
    root_migrations = product_path / "migrations"
    backend_migrations = backend_dir / "migrations"
    if root_migrations.exists() and not backend_migrations.exists():
        try:
            shutil.move(str(root_migrations), str(backend_migrations))
            logging.info(f"  📦 Moved migrations/ → backend/migrations/")
        except (PermissionError, OSError, shutil.Error) as e:
            logging.warning(f"  ⚠️  Failed to move migrations directory: {e}")
    elif root_migrations.exists() and backend_migrations.exists():
        # Check if backend migrations is empty (only __init__.py)
        backend_contents = [f for f in backend_migrations.iterdir() if f.name != "__pycache__"]
        if len(backend_contents) <= 1 and any(f.name == "__init__.py" for f in backend_contents):
            # Backend migrations is empty, move files from root
            try:
                for item in root_migrations.iterdir():
                    if item.name == "__pycache__":
                        continue
                    dest = backend_migrations / item.name
                    if not dest.exists() or dest.name == "__init__.py":
                        shutil.move(str(item), str(dest))
                        logging.info(f"  📦 Moved migrations/{item.name} → backend/migrations/{item.name}")
                # Remove empty root migrations directory
                root_migrations.rmdir()
                logging.info(f"  🗑️  Removed empty root migrations directory")
            except (PermissionError, OSError, shutil.Error) as e:
                logging.warning(f"  ⚠️  Failed to move migration files: {e}")
        else:
            logging.warning(f"  ⚠️  Both root and backend migrations have content, manual cleanup needed")

    # Ensure root __init__.py exists (needed for pytest imports)
    root_init = product_path / "__init__.py"
    if not root_init.exists():
        try:
            root_init.touch()
            logging.info(f"  📝 Created root __init__.py (needed for imports)")
        except (PermissionError, OSError) as e:
            logging.warning(f"  ⚠️  Failed to create root __init__.py: {e}")

    # Create or update apps.py (idempotent)
    apps_py = backend_dir / "apps.py"
    app_class_name = "".join(word.capitalize() for word in product_name.split("_"))
    expected_apps_content = f"""from django.apps import AppConfig


class {app_class_name}Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.{product_name}.backend"
    label = "{product_name}"
"""

    # Check if apps.py needs to be created or updated (with error handling)
    needs_update = True
    try:
        if apps_py.exists():
            current_content = apps_py.read_text()
            # Check if the expected config class already exists
            if f"class {app_class_name}Config(AppConfig):" in current_content:
                # Check if it has the correct name and label
                if (
                    f'name = "products.{product_name}.backend"' in current_content
                    and f'label = "{product_name}"' in current_content
                ):
                    needs_update = False
                    logging.info(f"  ℹ️  apps.py already has correct {app_class_name}Config")

        if needs_update:
            action = "Updated" if apps_py.exists() else "Created"
            apps_py.write_text(expected_apps_content)
            logging.info(f"  📝 {action} apps.py with {app_class_name}Config")
    except (PermissionError, OSError) as e:
        logging.exception(f"  ❌ Failed to create/update apps.py: {e}")

    logging.info(f"  ✅ {product_name} structure fixed!")


def update_django_settings(root_dir: Path, fixed_products: list[str]):
    """Update Django settings to use proper AppConfig paths for fixed products (idempotent)"""
    settings_file = root_dir / "posthog" / "settings" / "web.py"

    if not settings_file.exists():
        logging.warning(f"  ⚠️  Settings file not found: {settings_file}")
        return

    logging.info(f"  📝 Reading {settings_file}")

    try:
        content = settings_file.read_text()
    except (PermissionError, OSError) as e:
        logging.exception(f"  ❌ Failed to read settings file: {e}")
        return

    # Find the PRODUCTS_APPS list
    products_apps_pattern = r"PRODUCTS_APPS\s*=\s*\[(.*?)\]"
    match = re.search(products_apps_pattern, content, re.DOTALL)

    if not match:
        logging.warning("  ⚠️  Could not find PRODUCTS_APPS in settings")
        return

    apps_content = match.group(1)
    original_apps_content = apps_content

    # Track changes
    changes_made = False
    products_updated = []

    # Update each fixed product (idempotent)
    for product_name in fixed_products:
        app_class_name = "".join(word.capitalize() for word in product_name.split("_")) + "Config"
        new_entry = f'"products.{product_name}.backend.apps.{app_class_name}"'

        # Check if already using new format (idempotent check)
        if new_entry in apps_content:
            logging.info(f"  ℹ️  {product_name} already uses correct AppConfig format")
            continue

        # Look for the old format entry
        old_pattern = f'"products\\.{re.escape(product_name)}"'

        if re.search(old_pattern, apps_content):
            # Replace old with new
            apps_content = re.sub(old_pattern, new_entry, apps_content)
            changes_made = True
            products_updated.append(product_name)
            logging.info(f"  🔄 Updated {product_name} → {app_class_name}")
        else:
            # Product not found in PRODUCTS_APPS, could be missing or in different format
            # Check if product exists in any format
            product_pattern = f"products\\.{re.escape(product_name)}"
            if re.search(product_pattern, apps_content):
                logging.info(f"  ℹ️  {product_name} found in different format, skipping")
            else:
                logging.info(f"  ℹ️  {product_name} not found in PRODUCTS_APPS, may need manual addition")

    if changes_made:
        # Replace the PRODUCTS_APPS section in the full content
        new_content = content.replace(original_apps_content, apps_content)

        # Write back to file (with error handling)
        try:
            settings_file.write_text(new_content)
            logging.info(f"  ✅ Updated Django settings ({len(products_updated)} products)")
        except (PermissionError, OSError) as e:
            logging.exception(f"  ❌ Failed to write settings file: {e}")
    else:
        logging.info("  ℹ️  No settings updates needed")


if __name__ == "__main__":
    main()
