#!/usr/bin/env bash

set -e

# Generate schema.py from schema.json (temporary file, will be split)
TEMP_SCHEMA="posthog/schema_temp.py"
datamodel-codegen \
    --class-name='SchemaRoot' --collapse-root-models --target-python-version 3.11 --disable-timestamp \
    --use-one-literal-as-default --use-default --use-default-kwarg --use-subclass-enum \
    --input frontend/src/queries/schema.json --input-file-type jsonschema \
    --output "$TEMP_SCHEMA" --output-model-type pydantic_v2.BaseModel \
    --custom-file-header "# mypy: disable-error-code=\"assignment\"" \
    --set-default-enum-member --capitalise-enum-members \
    --wrap-string-literal

# Format temp schema
ruff format "$TEMP_SCHEMA"

# Check temp schema and autofix
ruff check --fix "$TEMP_SCHEMA"

# Replace class Foo(str, Enum) with class Foo(StrEnum) for proper handling in format strings in python 3.11
# Remove this when https://github.com/koxudaxi/datamodel-code-generator/issues/1313 is resolved
if sed --version 2>&1 | grep -q GNU; then
    # GNU sed
    sed -i -e 's/str, Enum/StrEnum/g' "$TEMP_SCHEMA"
    sed -i 's/from enum import Enum/from enum import Enum, StrEnum/g' "$TEMP_SCHEMA"
else
    # BSD/macOS sed
    sed -i '' -e 's/str, Enum/StrEnum/g' "$TEMP_SCHEMA"
    sed -i '' 's/from enum import Enum/from enum import Enum, StrEnum/g' "$TEMP_SCHEMA"
fi

# Move temp file to schema.py for splitting
mv "$TEMP_SCHEMA" posthog/schema.py

# Split schema.py into modules for faster imports
python3 bin/split-schema.py

# Format and check the split modules
for file in posthog/schema/*.py; do
    if [ -f "$file" ] && [ "$(basename "$file")" != "__pycache__" ]; then
        ruff format "$file"
        ruff check --fix "$file" || true
    fi
done

# Keep schema.py as a backup/reference (moved to schema/_generated.py by split script)
# The actual imports go through posthog/schema/__init__.py
