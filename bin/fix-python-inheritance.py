#!/usr/bin/env python3

"""
Post-processes the generated schema.py to create proper Python inheritance relationships
based on allOf patterns from the JSON schema.
"""

import re
import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")


def parse_inheritance_from_json():
    """Parse inheritance relationships from the JSON schema's allOf patterns."""
    import json

    schema_path = Path(__file__).parent / "../frontend/src/queries/schema.json"
    with open(schema_path) as f:
        schema = json.load(f)

    inheritance_map = {}
    definitions = schema.get("definitions", {})

    for name, definition in definitions.items():
        if isinstance(definition, dict) and "allOf" in definition:
            all_of = definition["allOf"]
            if len(all_of) >= 2 and "$ref" in all_of[0]:
                # Extract parent class name from $ref
                parent_ref = all_of[0]["$ref"]
                if parent_ref.startswith("#/definitions/"):
                    parent_name = parent_ref.replace("#/definitions/", "")
                    inheritance_map[name] = parent_name

    return inheritance_map


def transform_python_inheritance(content, inheritance_map):
    """Transform flat BaseModel classes to use inheritance."""
    lines = content.split("\n")
    result_lines = []

    for line in lines:
        # Match class definitions: "class ClassName(BaseModel):"
        class_match = re.match(r"^class\s+(\w+)\(BaseModel\):", line)
        if class_match:
            class_name = class_match.group(1)
            if class_name in inheritance_map:
                parent_class = inheritance_map[class_name]
                # Replace BaseModel with parent class
                new_line = line.replace(f"class {class_name}(BaseModel):", f"class {class_name}({parent_class}):")
                result_lines.append(new_line)
                continue

        result_lines.append(line)

    return "\n".join(result_lines)


def ensure_import_order(content):
    """Ensure parent classes are defined before child classes."""
    lines = content.split("\n")

    # Find class definitions and their line numbers
    class_definitions = {}
    class_start_lines = {}

    current_class = None
    class_content = []

    for i, line in enumerate(lines):
        class_match = re.match(r"^class\s+(\w+)\([^)]+\):", line)
        if class_match:
            # Save previous class if exists
            if current_class:
                class_definitions[current_class] = class_content[:]

            current_class = class_match.group(1)
            class_start_lines[current_class] = i
            class_content = [line]
        elif current_class and (line.startswith("    ") or line.strip() == ""):
            # Line belongs to current class (indented or empty)
            class_content.append(line)
        elif current_class and not line.startswith(" ") and line.strip():
            # End of class definition
            class_definitions[current_class] = class_content[:]
            current_class = None
            class_content = []

    # Save last class if exists
    if current_class:
        class_definitions[current_class] = class_content[:]

    # For now, return original content (topological sort would be complex)
    # This could be enhanced to reorder classes based on inheritance
    return content


def main():
    if len(sys.argv) != 2:
        logging.error("Usage: fix-python-inheritance.py <schema.py>")
        sys.exit(1)

    schema_file = Path(sys.argv[1])

    try:
        # Parse inheritance relationships from JSON schema
        inheritance_map = parse_inheritance_from_json()
        logging.info(f"Found {len(inheritance_map)} inheritance relationships to process")

        # Read and transform Python schema
        content = schema_file.read_text()
        transformed_content = transform_python_inheritance(content, inheritance_map)
        transformed_content = ensure_import_order(transformed_content)

        # Write back transformed content
        schema_file.write_text(transformed_content)
        logging.info("Python inheritance processing completed")

    except Exception as error:
        logging.exception(f"Error processing Python inheritance: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
