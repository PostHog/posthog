#!/usr/bin/env python3
"""
Phased migration orchestrator for model migrations.

Coordinates the complete migration process in discrete, trackable phases:
1. Prepare target structure (AppConfig, INSTALLED_APPS)
2. Move files 1:1 (git mv)
3. Update imports (import_rewriter.py)
4. Validate (Django --plan)
5. Generate Django migrations

Usage:
    python model_migration/migrate_phased.py --product data_warehouse
    python model_migration/migrate_phased.py --product data_warehouse --phase 2
    python model_migration/migrate_phased.py --product data_warehouse --resume
    python model_migration/migrate_phased.py --product data_warehouse --status
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional
import yaml

from phase_tracker import PhaseTracker, PhaseStatus
import import_rewriter
import django_helpers
import llm_migration_editor


# Phase definitions
PHASE_NAMES = [
    "prepare_structure",
    "move_files",
    "update_imports",
    "prepare_models",  # NEW: Fix ForeignKeys, db_table before validation
    "validate_django",
    "generate_migrations",
]


def run_command(cmd: List[str], description: str, check=True) -> subprocess.CompletedProcess:
    """Run a shell command and handle output."""
    print(f"\n▶ {description}")
    print(f"  $ {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}")

    return result


def phase_1_prepare_structure(config: dict, tracker: PhaseTracker) -> None:
    """
    Phase 1: Prepare target structure.
    - Create products/{product}/backend/ directories
    - Create AppConfig
    - Add to INSTALLED_APPS
    - Verify Django loads
    """
    print("\n" + "=" * 80)
    print("PHASE 1: Prepare Target Structure")
    print("=" * 80)

    tracker.start_phase(1)

    product = config["product"]
    target_base = config["target"]

    # Create target directory structure
    target_dir = Path(target_base.replace(".", "/"))
    operations = []

    # Create main directories
    dirs_to_create = [
        target_dir,
        target_dir / "models",
        target_dir / "api",
        target_dir / "migrations",
    ]

    for dir_path in dirs_to_create:
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            operations.append(f"mkdir -p {dir_path}")
            print(f"✓ Created {dir_path}")

    # Create __init__.py files
    init_files = [
        target_dir / "__init__.py",
        target_dir / "models" / "__init__.py",
        target_dir / "api" / "__init__.py",
        target_dir / "migrations" / "__init__.py",
    ]

    for init_file in init_files:
        if not init_file.exists():
            init_file.touch()
            operations.append(f"touch {init_file}")
            print(f"✓ Created {init_file}")

    # Create AppConfig
    apps_file = target_dir / "apps.py"
    app_label = product  # Keep underscores, e.g., "data_warehouse"
    class_name = "".join(word.capitalize() for word in product.split("_")) + "Config"

    if not apps_file.exists():
        apps_content = f'''"""Django app configuration for {product}."""
from django.apps import AppConfig


class {class_name}(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "{target_base}"
    label = "{app_label}"
'''
        apps_file.write_text(apps_content)
        operations.append(f"Created {apps_file}")
        print(f"✓ Created {apps_file}")

    # TODO: Add to INSTALLED_APPS in posthog/settings/web.py
    # This requires parsing and modifying Python, which we'll do manually for now
    print("\n⚠ Manual step required:")
    print(f"  Add '{target_base}.apps.{class_name}' to PRODUCTS_APPS in posthog/settings/web.py")

    tracker.complete_phase(1, operations=operations)
    print("\n✓ Phase 1 completed")


def phase_2_move_files(config: dict, tracker: PhaseTracker) -> None:
    """
    Phase 2: Move files 1:1.
    - Execute git mv for each file in file_moves
    - Preserve directory structure
    """
    print("\n" + "=" * 80)
    print("PHASE 2: Move Files 1:1")
    print("=" * 80)

    tracker.start_phase(2)

    file_moves = config.get("file_moves", [])
    operations = []
    files_modified = []

    for move in file_moves:
        source = Path(move["from"])
        target = Path(move["to"])

        if not source.exists():
            print(f"⚠ Skipping {source} (does not exist)")
            continue

        # Create parent directory for target
        target.parent.mkdir(parents=True, exist_ok=True)

        # If target exists, remove it first (handles __init__.py created by Phase 1)
        if target.exists():
            print(f"  ⚠ Target exists, removing: {target}")
            target.unlink()
            operations.append(f"rm {target}")

        # Execute git mv
        try:
            run_command(
                ["git", "mv", str(source), str(target)],
                f"Move {source} → {target}",
            )
            operations.append(f"git mv {source} {target}")
            files_modified.append(str(target))
        except RuntimeError as e:
            print(f"❌ Failed to move {source}: {e}")
            tracker.fail_phase(2, str(e))
            return

    tracker.complete_phase(2, files_modified=files_modified, operations=operations)
    print(f"\n✓ Phase 2 completed - moved {len(files_modified)} files")


def phase_3_update_imports(config: dict, tracker: PhaseTracker) -> None:
    """
    Phase 3: Update imports.
    - Run import_rewriter.py with moves.yml
    - Rewrite all imports in codebase
    """
    print("\n" + "=" * 80)
    print("PHASE 3: Update Imports")
    print("=" * 80)

    tracker.start_phase(3)

    # Load moves.yml for import rewriting
    moves_path = Path("model_migration/moves.yml")
    if not moves_path.exists():
        error = f"moves.yml not found at {moves_path}"
        print(f"❌ {error}")
        tracker.fail_phase(3, error)
        return

    module_moves, symbol_exports = import_rewriter.load_moves_config(moves_path)

    # Rewrite imports in entire tree
    root = Path(".")
    try:
        modified_count = import_rewriter.rewrite_imports_in_tree(
            root=root,
            module_moves=module_moves,
            symbol_exports=symbol_exports,
            dry_run=False,
        )

        tracker.complete_phase(
            3,
            files_modified=[f"{modified_count} files updated"],
            operations=["import_rewriter.py --write"],
        )
        print(f"\n✓ Phase 3 completed - updated imports in {modified_count} files")

    except Exception as e:
        print(f"❌ Import rewriting failed: {e}")
        tracker.fail_phase(3, str(e))
        raise


def phase_4_prepare_models(config: dict, tracker: PhaseTracker) -> None:
    """
    Phase 4: Prepare Django models for validation.
    - Extract model names from moved files
    - Fix ForeignKey string references
    - Ensure db_table declarations

    This prepares models so Phase 5 validation will pass.
    """
    print("\n" + "=" * 80)
    print("PHASE 4: Prepare Django Models")
    print("=" * 80)

    tracker.start_phase(4)

    product = config["product"]
    target_base = config["target"]
    target_dir = Path(target_base.replace(".", "/"))
    models_dir = target_dir / "models"

    # Get app label from apps.py (should match product name with underscores)
    app_label = product  # e.g., "data_warehouse"

    operations = []

    try:
        # Step 1: Extract model names from moved files
        print("\n1. Discovering model classes...")
        model_names = set()

        if models_dir.exists():
            for py_file in models_dir.glob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                models = django_helpers.extract_model_names(py_file)
                model_names.update(models)
                if models:
                    print(f"   Found models in {py_file.name}: {', '.join(models)}")

        print(f"   Total models discovered: {len(model_names)}")
        operations.append(f"Discovered {len(model_names)} models")

        if not model_names:
            print("⚠️  No models found - skipping preparation")
            tracker.complete_phase(4, operations=operations)
            return

        # Step 2: Fix ForeignKey references
        print("\n2. Fixing ForeignKey references...")
        fk_modified_count = 0

        if models_dir.exists():
            for py_file in models_dir.glob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                if django_helpers.fix_foreign_keys_in_file(py_file, model_names, app_label):
                    print(f"   ✓ Fixed ForeignKeys in {py_file.name}")
                    fk_modified_count += 1

        print(f"   Modified {fk_modified_count} files with ForeignKey updates")
        operations.append(f"Fixed ForeignKeys in {fk_modified_count} files")

        # Step 3: Ensure db_table declarations
        print("\n3. Ensuring db_table declarations...")
        db_table_modified_count = 0

        if models_dir.exists():
            for py_file in models_dir.glob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                if django_helpers.ensure_model_db_tables(py_file):
                    print(f"   ✓ Updated {py_file.name}")
                    db_table_modified_count += 1

        print(f"   Modified {db_table_modified_count} files with db_table declarations")
        operations.append(f"Added db_table to {db_table_modified_count} files")

        tracker.complete_phase(4, operations=operations)
        print("\n✓ Phase 4 completed - models prepared for Django validation")

    except Exception as e:
        print(f"❌ Model preparation failed: {e}")
        tracker.fail_phase(4, str(e))
        raise


def phase_5_validate_django(config: dict, tracker: PhaseTracker) -> None:
    """
    Phase 5: Validate with Django.
    - Run python manage.py migrate --plan
    - Ensure Django loads without errors
    """
    print("\n" + "=" * 80)
    print("PHASE 5: Validate Django")
    print("=" * 80)

    tracker.start_phase(5)

    try:
        result = run_command(
            ["python", "manage.py", "migrate", "--plan"],
            "Validate Django with migrate --plan",
            check=False,
        )

        if result.returncode != 0:
            error = f"Django validation failed with exit code {result.returncode}\n{result.stderr}"
            print(f"❌ {error}")
            tracker.fail_phase(5, error)
            return

        tracker.complete_phase(5, operations=["python manage.py migrate --plan"])
        print("\n✓ Phase 5 completed - Django validation passed")

    except Exception as e:
        print(f"❌ Django validation failed: {e}")
        tracker.fail_phase(5, str(e))
        raise


def phase_6_generate_migrations(config: dict, tracker: PhaseTracker) -> None:
    """
    Phase 6: Generate Django migrations (postprocess).
    - Discover model names (for LLM editing)
    - Generate product app migration
    - Generate posthog removal migration
    - LLM edit both migrations

    Note: Model preparation (ForeignKeys, db_table) was done in Phase 4.
    """
    print("\n" + "=" * 80)
    print("PHASE 6: Generate Django Migrations")
    print("=" * 80)

    tracker.start_phase(6)

    product = config["product"]
    target_base = config["target"]
    target_dir = Path(target_base.replace(".", "/"))
    models_dir = target_dir / "models"

    operations = []

    try:
        # Step 1: Discover model names (needed for LLM editing)
        print("\n1. Discovering model classes for LLM editing...")
        model_names = set()

        if models_dir.exists():
            for py_file in models_dir.glob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                models = django_helpers.extract_model_names(py_file)
                model_names.update(models)

        print(f"   Found {len(model_names)} models")

        if not model_names:
            print("⚠️  No models found - skipping migration generation")
            tracker.complete_phase(6, operations=operations)
            return

        # Step 2: Generate product app migration
        print(f"\n2. Generating migration for {product}...")
        result = run_command(
            ["python", "manage.py", "makemigrations", product, "-n", f"migrate_{product}_models"],
            f"Generate migration for {product}",
            check=False,
        )

        if result.returncode != 0:
            error = f"Product migration generation failed: {result.stderr}"
            print(f"❌ {error}")
            tracker.fail_phase(6, error)
            return

        operations.append(f"Generated {product} migration")

        # Step 3: Generate posthog removal migration
        print(f"\n3. Generating posthog removal migration...")
        result = run_command(
            ["python", "manage.py", "makemigrations", "posthog", "-n", f"remove_{product}_models"],
            "Generate posthog removal migration",
            check=False,
        )

        if result.returncode != 0:
            error = f"Posthog migration generation failed: {result.stderr}"
            print(f"❌ {error}")
            tracker.fail_phase(6, error)
            return

        operations.append("Generated posthog removal migration")

        # Step 4: Edit migrations with LLM
        print(f"\n4. Editing migrations with Claude CLI...")

        # Determine app label (lowercase, no underscores)
        app_label = product.replace("_", "")

        # Get migration directories
        product_migrations_dir = target_dir / "migrations"
        posthog_migrations_dir = Path("posthog/migrations")

        # Convert model names to list
        model_names_list = sorted(model_names)

        try:
            product_success, posthog_success = llm_migration_editor.edit_migrations(
                product=product,
                target_app=app_label,
                model_names=model_names_list,
                product_migrations_dir=product_migrations_dir,
                posthog_migrations_dir=posthog_migrations_dir,
            )

            if product_success and posthog_success:
                operations.append("Successfully edited both migrations with Claude")
                print("\n✅ Both migrations edited successfully")
            elif product_success or posthog_success:
                operations.append("Partially edited migrations with Claude")
                print("\n⚠️  Some migrations edited successfully, others need manual review")
            else:
                operations.append("LLM editing failed - manual review required")
                print("\n⚠️  LLM editing failed - manual review of migrations required")
        except Exception as e:
            print(f"\n⚠️  LLM editing error: {e}")
            operations.append(f"LLM editing error: {e}")

        # Step 5: Provide next steps
        print("\n" + "=" * 80)
        print("✓ Phase 6 completed - migrations generated and edited")
        print("=" * 80)
        print("\n📋 Next steps:")
        print("\n1. Review edited migrations:")
        print(f"   - products/{product}/backend/migrations/")
        print("   - posthog/migrations/")
        print("\n2. Verify migration patterns:")
        print("   - Product migration: Uses SeparateDatabaseAndState")
        print("   - Posthog migration: Contains ContentType update (RunPython)")
        print("\n3. Test migrations:")
        print("   python manage.py migrate --plan")
        print("\n4. If migrations look good, you can apply them or create PR")

        tracker.complete_phase(6, operations=operations)

    except Exception as e:
        print(f"❌ Migration generation failed: {e}")
        tracker.fail_phase(6, str(e))
        raise


# Phase execution map
PHASE_FUNCTIONS = {
    1: phase_1_prepare_structure,
    2: phase_2_move_files,
    3: phase_3_update_imports,
    4: phase_4_prepare_models,
    5: phase_5_validate_django,
    6: phase_6_generate_migrations,
}


def execute_phase(phase_id: int, config: dict, tracker: PhaseTracker) -> bool:
    """
    Execute a single phase.

    Returns True if successful, False if failed.
    """
    phase_func = PHASE_FUNCTIONS.get(phase_id)
    if not phase_func:
        print(f"❌ Unknown phase {phase_id}")
        return False

    try:
        phase_func(config, tracker)
        return True
    except Exception as e:
        print(f"❌ Phase {phase_id} failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Phased migration orchestrator"
    )
    parser.add_argument(
        "--product",
        required=True,
        help="Product name (e.g., data_warehouse)",
    )
    parser.add_argument(
        "--phase",
        type=int,
        help="Run specific phase only (1-5)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last failed or pending phase",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current migration status",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset all phases to pending",
    )

    args = parser.parse_args()

    # Load configuration
    moves_path = Path("model_migration/moves.yml")
    if not moves_path.exists():
        print(f"Error: moves.yml not found at {moves_path}", file=sys.stderr)
        print("Run: python model_migration/move_scanner.py --product {args.product}")
        return 1

    with open(moves_path, "r") as f:
        config = yaml.safe_load(f)

    # Initialize phase tracker
    tracker_path = Path("model_migration/phase_tracker.yml")
    tracker = PhaseTracker(tracker_path)

    # Handle status command
    if args.status:
        tracker.load()
        tracker.print_status()
        return 0

    # Handle reset command
    if args.reset:
        tracker.load()
        tracker.reset()
        print("✓ Reset all phases to pending")
        return 0

    # Initialize or load tracker
    if not tracker_path.exists():
        print(f"Initializing phase tracker for {args.product}")
        tracker.initialize(args.product, PHASE_NAMES)
    else:
        tracker.load()

    # Handle resume mode
    if args.resume:
        next_phase = tracker.get_next_pending_phase()
        if next_phase is None:
            print("✓ All phases completed!")
            return 0

        print(f"Resuming from phase {next_phase.id}: {next_phase.name}")
        phase_to_run = next_phase.id

    # Handle specific phase mode
    elif args.phase:
        phase_to_run = args.phase
        print(f"Running phase {phase_to_run}")

    # Default: run all phases sequentially
    else:
        print(f"Running all phases for {args.product}")
        for phase_id in range(1, len(PHASE_NAMES) + 1):
            success = execute_phase(phase_id, config, tracker)
            if not success:
                print(f"\n❌ Migration failed at phase {phase_id}")
                print(f"To resume: python model_migration/migrate_phased.py --product {args.product} --resume")
                return 1

        print("\n" + "=" * 80)
        print("✓ All phases completed successfully!")
        print("=" * 80)
        return 0

    # Execute single phase
    success = execute_phase(phase_to_run, config, tracker)
    if not success:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
