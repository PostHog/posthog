#!/usr/bin/env python3

"""
Fix inheritance for AnalyticsQueryResponseBase subclasses.
Reads schema-general.ts to find classes that extend AnalyticsQueryResponseBase.
"""

import re
import sys
from pathlib import Path


def get_analytics_response_classes(schema_ts_path: Path):
    """Find all classes that extend AnalyticsQueryResponseBase in the TypeScript schema."""

    if not schema_ts_path.exists():
        print(f"Warning: {schema_ts_path} not found")  # noqa: T201
        return []

    with open(schema_ts_path) as f:
        content = f.read()

    # Find all interfaces/classes that extend AnalyticsQueryResponseBase
    pattern = r"export interface (\w+) extends AnalyticsQueryResponseBase"
    matches = re.findall(pattern, content)

    print(f"Found {len(matches)} classes that extend AnalyticsQueryResponseBase: {matches}")  # noqa: T201
    return matches


def fix_inheritance(schema_path: Path, schema_ts_path: Path):
    """Fix inheritance by changing BaseModel to AnalyticsQueryResponseBase for classes found in TypeScript."""

    # Get the list of classes that should inherit from AnalyticsQueryResponseBase
    analytics_response_classes = get_analytics_response_classes(schema_ts_path)

    if not analytics_response_classes:
        print("No classes found that extend AnalyticsQueryResponseBase")  # noqa: T201
        return

    with open(schema_path) as f:
        content = f.read()

    # Find the position of AnalyticsQueryResponseBase definition
    base_class_pos = content.find("class AnalyticsQueryResponseBase(BaseModel):")
    if base_class_pos == -1:
        print("Warning: AnalyticsQueryResponseBase not found in schema file")  # noqa: T201
        return

    # For each analytics response class, change BaseModel to AnalyticsQueryResponseBase
    changes_made = 0
    for class_name in analytics_response_classes:
        old_declaration = f"class {class_name}(BaseModel):"
        class_pos = content.find(old_declaration)

        if class_pos != -1:
            if class_pos > base_class_pos:
                # Class is defined after AnalyticsQueryResponseBase, safe to change
                new_declaration = f"class {class_name}(AnalyticsQueryResponseBase):"
                content = content.replace(old_declaration, new_declaration)
                changes_made += 1
            else:
                print(f"Warning: {class_name} is defined before AnalyticsQueryResponseBase, skipping")  # noqa: T201
        else:
            print(f"Warning: {class_name} not found in generated Python schema")  # noqa: T201

    with open(schema_path, "w") as f:
        f.write(content)

    print(f"Fixed inheritance for {changes_made} classes in {schema_path}")  # noqa: T201


def main():
    if len(sys.argv) != 2:
        print("Usage: python fix-schema-inheritance.py <schema.py path>")  # noqa: T201
        sys.exit(1)

    schema_path = Path(sys.argv[1])
    if not schema_path.exists():
        print(f"Error: {schema_path} does not exist")  # noqa: T201
        sys.exit(1)

    # Find the schema TypeScript file
    schema_ts_path = Path("frontend/src/queries/schema/schema-general.ts")

    fix_inheritance(schema_path, schema_ts_path)


if __name__ == "__main__":
    main()
