"""
LLM-assisted migration file editing.

Ported from migrate_models.py - uses Claude CLI to automatically edit
generated Django migrations to follow proper patterns.
"""

import re
import subprocess
from pathlib import Path
from typing import Optional


class LLMLimitReachedError(Exception):
    """Raised when an AI provider reports that a usage limit has been reached."""
    pass


class LLMInvocationError(Exception):
    """Raised when invoking an AI provider fails for runtime reasons."""
    pass


LLM_LIMIT_MARKERS = [
    "rate limit",
    "limit reached",
    "out of credits",
    "usage limit",
    "quota",
]


def call_llm_cli(tool: str, prompt: str, file_content: str) -> str:
    """
    Invoke an AI CLI tool and return its stdout.

    Args:
        tool: "claude" or "codex"
        prompt: The prompt to send
        file_content: The file content to edit

    Returns:
        stdout from the CLI tool

    Raises:
        LLMLimitReachedError: If usage limit reached
        LLMInvocationError: If invocation fails
    """
    if tool == "claude":
        command = ["claude", "-p", prompt]
    elif tool == "codex":
        command = ["codex", "exec", prompt]
    else:
        raise ValueError(f"Unsupported LLM tool: {tool}")

    result = subprocess.run(
        command,
        input=file_content,
        capture_output=True,
        text=True,
    )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    combined_output = "\n".join(part for part in [stdout, stderr] if part).strip()

    if any(marker in combined_output.lower() for marker in LLM_LIMIT_MARKERS):
        raise LLMLimitReachedError(combined_output or "Usage limit reached")

    if result.returncode != 0:
        raise LLMInvocationError(combined_output or f"{tool} invocation failed")

    return stdout


def extract_updated_content(llm_output: str) -> str:
    """
    Pull the updated file contents out of a fenced code block, if present.

    Args:
        llm_output: Raw output from LLM

    Returns:
        Extracted code content
    """
    code_block_match = re.search(r"```(?:python)?\n(.*?)\n```", llm_output, flags=re.DOTALL)
    if code_block_match:
        return code_block_match.group(1)
    return llm_output


def apply_llm_edit(file_path: Path, prompt: str) -> bool:
    """
    Apply an edit to a file using Claude with Codex fallback.

    Args:
        file_path: Path to file to edit
        prompt: Instructions for the edit

    Returns:
        True if edit succeeded, False otherwise
    """
    if not file_path.exists():
        print(f"⚠️  File not found for AI edit: {file_path}")
        return False

    original_content = file_path.read_text()

    prompt_with_instructions = (
        f"{prompt}\n\n"
        "Respond with only the full updated file contents inside a single fenced code block labelled python (```python ... ```), with no other commentary."
    )

    used_tool = "Claude"

    print(f"🤖 Invoking {used_tool} for AI-assisted edit on {file_path}")

    try:
        raw_output = call_llm_cli("claude", prompt_with_instructions, original_content)
    except LLMLimitReachedError as limit_error:
        print(f"⚠️  Claude limit reached ({limit_error}); attempting Codex fallback...")
        try:
            raw_output = call_llm_cli("codex", prompt_with_instructions, original_content)
            used_tool = "Codex"
        except LLMLimitReachedError as codex_limit:
            print(f"⚠️  Codex also reported a limit: {codex_limit}")
            return False
        except LLMInvocationError as codex_error:
            print(f"⚠️  Codex invocation failed: {codex_error}")
            return False
    except LLMInvocationError as error:
        print(f"⚠️  Claude invocation failed: {error}")
        return False

    updated_content = extract_updated_content(raw_output).rstrip()

    if not updated_content:
        print("⚠️  AI response did not contain updated content")
        return False

    file_path.write_text(updated_content + "\n")
    print(f"✅ Applied AI edit with {used_tool} on {file_path}")
    return True


def edit_product_migration(migration_path: Path) -> bool:
    """
    Edit product app migration to follow SeparateDatabaseAndState pattern.

    Args:
        migration_path: Path to the product migration file

    Returns:
        True if edit succeeded
    """
    prompt = (
        f"Please edit the Django migration at {migration_path} to follow the exact proven pattern from "
        "products/batch_exports/migrations/0001_initial.py. Make the migration look structurally identical to that file, "
        "with only model names and fields differing:\n\n"
        "1. Wrap ALL operations in a single migrations.SeparateDatabaseAndState block.\n"
        "   - Do not leave any operations at the top level.\n\n"
        "2. Place every schema/state operation (CreateModel, AddConstraint, AddField, AlterField, etc.) "
        "inside the state_operations list.\n\n"
        "3. The database_operations list must contain exactly one element: the comment "
        "'# No database operations - table already exists with this name'. "
        "Do not add any RunSQL, RunPython, or other operations.\n\n"
        "4. Preserve the existing db_table configuration so the model continues using the original table.\n\n"
        "5. Do NOT set managed=False. Keep the model fully managed (managed=True is implicit).\n\n"
        "6. Do NOT introduce any changes not present in the original migration (dependencies, imports, or extra operations).\n\n"
        "In summary: the final migration must mirror products/batch_exports/migrations/0001_initial.py in structure, "
        "with only the model definitions differing."
    )

    return apply_llm_edit(migration_path, prompt)


def edit_posthog_migration(migration_path: Path, target_app: str, model_names: list[str]) -> bool:
    """
    Edit posthog removal migration to add ContentType updates.

    Args:
        migration_path: Path to the posthog migration file
        target_app: Target app label (e.g., "data_warehouse")
        model_names: List of model class names being moved

    Returns:
        True if edit succeeded
    """
    # Convert model names to lowercase for ContentType
    lowercase_models = [name.lower() for name in model_names]
    models_list = ", ".join(f"'{m}'" for m in lowercase_models)

    prompt = (
        f"You are given a Django migration file at {migration_path}. Edit it EXACTLY as follows:\n\n"
        "1. At the top of the file, immediately after the imports, insert ONE helper function:\n"
        "   def update_content_type(apps, schema_editor):\n"
        "       ContentType = apps.get_model('contenttypes', 'ContentType')\n"
        f"       for model in [{models_list}]:\n"
        "           try:\n"
        "               ct = ContentType.objects.get(app_label='posthog', model=model)\n"
        f"               ct.app_label = '{target_app}'\n"
        "               ct.save()\n"
        "           except ContentType.DoesNotExist:\n"
        "               pass\n\n"
        "   def reverse_content_type(apps, schema_editor):\n"
        "       ContentType = apps.get_model('contenttypes', 'ContentType')\n"
        f"       for model in [{models_list}]:\n"
        "           try:\n"
        f"               ct = ContentType.objects.get(app_label='{target_app}', model=model)\n"
        "               ct.app_label = 'posthog'\n"
        "               ct.save()\n"
        "           except ContentType.DoesNotExist:\n"
        "               pass\n\n"
        "2. No model should actually be deleted in this migration:\n"
        "   - Wrap ALL operations in a single migrations.SeparateDatabaseAndState block.\n"
        "   - Place RunPython(update_content_type, reverse_content_type) ONLY in database_operations.\n"
        "   - Do NOT drop any database tables or columns.\n\n"
        "3. Do not duplicate update_content_type. It must be defined once and referenced in SeparateDatabaseAndState.\n\n"
        "4. The final migration must:\n"
        "   - Delete and alter any fields and the models in state only (so Django no longer tracks them under 'posthog').\n"
        "   - Keep the underlying database tables intact.\n"
        "   - Update django_content_type rows so they point to the new app label.\n\n"
        "5. Do not make ANY other changes. Keep dependencies, imports, and class Migration exactly as they are except for the required edits above.\n"
    )

    return apply_llm_edit(migration_path, prompt)


def find_latest_migration(migrations_dir: Path) -> Optional[Path]:
    """
    Find the most recent migration file in a directory.

    Args:
        migrations_dir: Path to migrations directory

    Returns:
        Path to latest migration, or None if none found
    """
    if not migrations_dir.exists():
        return None

    migrations = sorted([
        f for f in migrations_dir.iterdir()
        if f.suffix == ".py" and f.name != "__init__.py"
    ])

    if not migrations:
        return None

    return migrations[-1]


def edit_migrations(
    product: str,
    target_app: str,
    model_names: list[str],
    product_migrations_dir: Path,
    posthog_migrations_dir: Path,
) -> tuple[bool, bool]:
    """
    Edit both product and posthog migrations using LLM.

    Args:
        product: Product name (e.g., "data_warehouse")
        target_app: Target app label (e.g., "datawarehouse")
        model_names: List of model class names being moved
        product_migrations_dir: Path to product migrations directory
        posthog_migrations_dir: Path to posthog migrations directory

    Returns:
        Tuple of (product_edit_succeeded, posthog_edit_succeeded)
    """
    print("\n🤖 Using Claude CLI to edit migrations...")

    product_success = True
    posthog_success = True

    # Edit product migration
    product_migration = find_latest_migration(product_migrations_dir)
    if product_migration:
        print(f"\n📝 Editing product migration: {product_migration.name}")
        product_success = edit_product_migration(product_migration)
        if not product_success:
            print("⚠️  Automated edit for product migration failed; manual review needed")
    else:
        print("⚠️  No product migration found")
        product_success = False

    # Edit posthog migration
    posthog_migration = find_latest_migration(posthog_migrations_dir)
    if posthog_migration:
        print(f"\n📝 Editing posthog migration: {posthog_migration.name}")
        posthog_success = edit_posthog_migration(posthog_migration, target_app, model_names)
        if not posthog_success:
            print("⚠️  Automated edit for posthog migration failed; manual review needed")
    else:
        print("⚠️  No posthog migration found")
        posthog_success = False

    return product_success, posthog_success
