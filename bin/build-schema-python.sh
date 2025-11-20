#!/usr/bin/env bash

set -e

# Generate schema/_generated.py from schema.json
datamodel-codegen \
    --class-name='SchemaRoot' --collapse-root-models --target-python-version 3.11 --disable-timestamp \
    --use-one-literal-as-default --use-default --use-default-kwarg --use-subclass-enum \
    --input frontend/src/queries/schema.json --input-file-type jsonschema \
    --output posthog/schema/_generated.py --output-model-type pydantic_v2.BaseModel \
    --custom-file-header "# mypy: disable-error-code=\"assignment\"" \
    --set-default-enum-member --capitalise-enum-members \
    --wrap-string-literal

# Format schema/_generated.py
ruff format posthog/schema/_generated.py

# Check schema/_generated.py and autofix
ruff check --fix posthog/schema/_generated.py

# Replace class Foo(str, Enum) with class Foo(StrEnum) for proper handling in format strings in python 3.11
# Remove this when https://github.com/koxudaxi/datamodel-code-generator/issues/1313 is resolved
if sed --version 2>&1 | grep -q GNU; then
    # GNU sed
    sed -i -e 's/str, Enum/StrEnum/g' posthog/schema/_generated.py
    sed -i 's/from enum import Enum/from enum import Enum, StrEnum/g' posthog/schema/_generated.py
else
    # BSD/macOS sed
    sed -i '' -e 's/str, Enum/StrEnum/g' posthog/schema/_generated.py
    sed -i '' 's/from enum import Enum/from enum import Enum, StrEnum/g' posthog/schema/_generated.py
fi
