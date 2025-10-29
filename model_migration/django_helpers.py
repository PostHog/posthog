"""
Django-specific helpers for model migrations.

Ported from migrate_models.py to support phased migration system.
"""

import re
import ast
from pathlib import Path


def extract_model_names(file_path: Path) -> set[str]:
    """
    Extract Django model class names from a Python file.

    Returns set of class names that appear to be Django models.
    """
    try:
        content = file_path.read_text()
        tree = ast.parse(content)
    except (FileNotFoundError, SyntaxError):
        return set()

    model_names = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if this is likely a Django model
            is_model = any(
                (isinstance(base, ast.Attribute) and base.attr.endswith("Model"))
                or (isinstance(base, ast.Name) and base.id.endswith("Model"))
                for base in node.bases
            )
            if is_model:
                model_names.add(node.name)

    return model_names


def ensure_model_db_tables(models_path: Path) -> bool:
    """
    Ensure moved models keep referencing the original database tables.

    Adds db_table declarations to Meta classes for all Django models.

    Returns True if file was modified.
    """
    try:
        source = models_path.read_text()
    except FileNotFoundError:
        return False

    try:
        tree = ast.parse(source)
    except SyntaxError:
        print(f"⚠️  Failed to parse {models_path} for db_table injection")  # noqa: T201
        return False

    lines = source.splitlines()
    insertions: list[tuple[int, list[str]]] = []

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        class_name = node.name
        expected_table = f"posthog_{class_name.lower()}"

        # Only add Meta class to Django Model classes
        is_model_class = any(
            isinstance(base, ast.Name)
            and base.id.endswith("Model")
            or isinstance(base, ast.Attribute)
            and base.attr.endswith("Model")
            for base in node.bases
        )
        if not is_model_class:
            continue

        # Check if Meta class exists
        meta_class = next(
            (stmt for stmt in node.body if isinstance(stmt, ast.ClassDef) and stmt.name == "Meta"),
            None,
        )

        if meta_class:
            # Check if db_table already exists
            has_db_table = False
            for stmt in meta_class.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id == "db_table":
                            has_db_table = True
                            break
                elif isinstance(stmt, ast.AnnAssign):
                    target = stmt.target
                    if isinstance(target, ast.Name) and target.id == "db_table":
                        has_db_table = True
                if has_db_table:
                    break

            if has_db_table:
                continue

            # Add db_table to existing Meta class
            if meta_class.body:
                indent_line = lines[meta_class.body[0].lineno - 1]
                indent = indent_line[: len(indent_line) - len(indent_line.lstrip())]
                insert_after = meta_class.body[-1].end_lineno
            else:
                meta_line = lines[meta_class.lineno - 1]
                meta_indent = meta_line[: len(meta_line) - len(meta_line.lstrip())]
                indent = meta_indent + "    "
                insert_after = meta_class.lineno

            insertions.append((insert_after, [f'{indent}db_table = "{expected_table}"']))
        else:
            # Create new Meta class
            class_line = lines[node.lineno - 1]
            class_indent = class_line[: len(class_line) - len(class_line.lstrip())]
            body_indent = class_indent + "    "

            # Place Meta class after all fields but before methods
            insert_after = node.lineno
            if node.body:
                # Find the last field assignment (before any method definitions)
                last_field_line = node.lineno
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign) or isinstance(stmt, ast.AnnAssign):
                        last_field_line = stmt.end_lineno
                    elif isinstance(stmt, ast.FunctionDef):
                        break  # Stop at first method
                insert_after = last_field_line

            insert_block = [
                "",
                f"{body_indent}class Meta:",
                f'{body_indent}    db_table = "{expected_table}"',
            ]
            insertions.append((insert_after, insert_block))

    if not insertions:
        return False

    # Apply insertions in reverse order to preserve line numbers
    for insert_after, block in sorted(insertions, key=lambda item: item[0], reverse=True):
        index = insert_after
        lines[index:index] = block

    models_path.write_text("\n".join(lines) + "\n")
    return True


def update_foreign_key_references(line: str, model_names: set[str], app_label: str) -> str:
    """
    Update ForeignKey references to include app label prefix.

    Args:
        line: Line of Python code
        model_names: Set of model names being moved (don't prefix these)
        app_label: Target app label (e.g., "data_warehouse")

    Returns:
        Updated line with proper app label prefixes
    """
    # FIRST: Check if this line is a dictionary definition - don't modify dictionary keys
    # Dictionary pattern: "Key": value or 'Key': value
    # This check must run BEFORE any other regex patterns to prevent corruption
    if re.search(r"""["'][A-Z][a-zA-Z]*["']\s*:""", line):
        return line  # Skip dictionary definitions entirely

    # First handle direct class references: ForeignKey(ClassName, ...)
    direct_pattern = r"\b(ForeignKey|ManyToManyField|OneToOneField)\(([A-Z][a-zA-Z]*)([\),])"

    def replace_direct(match):
        field_type = match.group(1)
        model_ref = match.group(2)
        delimiter = match.group(3)

        # Don't change if it's a model being moved
        if model_ref in model_names:
            return match.group(0)

        # Convert to string reference with posthog prefix
        return f'{field_type}("posthog.{model_ref}"{delimiter}'

    line = re.sub(direct_pattern, replace_direct, line)

    # Handle "posthog.ModelName" references - change to "datawarehouse.ModelName" if model is moving
    posthog_prefixed_pattern = r'"posthog\.([A-Z][a-zA-Z]*)"'

    def replace_posthog_prefixed(match):
        model_ref = match.group(1)
        # If this model is being moved, change to target app label
        if model_ref in model_names:
            return f'"{app_label}.{model_ref}"'
        # Otherwise keep posthog prefix
        return match.group(0)

    line = re.sub(posthog_prefixed_pattern, replace_posthog_prefixed, line)

    # Handle existing incorrect app label references (e.g., "datawarehouse." → "data_warehouse.")
    # This catches any app label that doesn't match the current one
    incorrect_label_pattern = r'"([a-z_]+)\.([A-Z][a-zA-Z]*)"'

    def replace_incorrect_label(match):
        old_label = match.group(1)
        model_ref = match.group(2)

        # If this model is one we're managing and the label is wrong, fix it
        if model_ref in model_names and old_label != app_label:
            return f'"{app_label}.{model_ref}"'

        # Otherwise keep as is
        return match.group(0)

    line = re.sub(incorrect_label_pattern, replace_incorrect_label, line)

    # Then handle existing unprefixed string references
    # Pattern to match quoted model references in field definitions
    # Matches: "ModelName" but not "posthog.ModelName" or "datawarehouse.ModelName"
    pattern = r'"([A-Z][a-zA-Z]*)"'

    def replace_reference(match):
        model_ref = match.group(1)
        # Don't prefix if it's one of our models being moved, or already has a prefix
        if model_ref in model_names or "." in model_ref:
            return match.group(0)  # Return unchanged
        # Add posthog. prefix for references to models staying in posthog
        return f'"posthog.{model_ref}"'

    return re.sub(pattern, replace_reference, line)


def fix_foreign_keys_in_file(file_path: Path, model_names: set[str], app_label: str) -> bool:
    """
    Update ForeignKey references in a Python file.

    Args:
        file_path: Path to Python file
        model_names: Set of model names being moved
        app_label: Target app label (e.g., "data_warehouse")

    Returns True if file was modified.
    """
    try:
        lines = file_path.read_text().splitlines()
    except FileNotFoundError:
        return False

    modified = False
    updated_lines = []

    for line in lines:
        updated_line = update_foreign_key_references(line, model_names, app_label)
        if updated_line != line:
            modified = True
        updated_lines.append(updated_line)

    if modified:
        file_path.write_text("\n".join(updated_lines) + "\n")

    return modified
