#!/usr/bin/env bash

set -e

# Generate schema.py from schema.json
datamodel-codegen \
    --class-name='SchemaRoot' --collapse-root-models --target-python-version 3.10 --disable-timestamp \
    --use-one-literal-as-default --use-default --use-default-kwarg --use-subclass-enum \
    --input frontend/src/queries/schema.json --input-file-type jsonschema \
    --output posthog/schema.py --output-model-type pydantic_v2.BaseModel \
    --custom-file-header "# mypy: disable-error-code=\"assignment\"" \
    --set-default-enum-member

# Format schema.py
ruff format posthog/schema.py

# Check schema.py and autofix
ruff check --fix posthog/schema.py

# HACK: Datamodel-codegen output for enum-type fields with a default is invalid – the default value is a plain string,
# and not the expected enum member. We fix this using sed, which is pretty hacky, but does the job.
# Specifically, we need to replace `Optional[PropertyOperator] = "exact"`
# with `Optional[PropertyOperator] = PropertyOperator("exact")` to make the default value valid.
# Remove this when https://github.com/koxudaxi/datamodel-code-generator/issues/1929 is resolved.
if [[ "$OSTYPE" == "darwin"* ]]; then
    # sed needs `-i` to be followed by `''` on macOS
    sed -i '' -e 's/Optional\[PropertyOperator\] = \("[A-Za-z_]*"\)/Optional[PropertyOperator] = PropertyOperator(\1)/g' posthog/schema.py
else
    sed -i -e 's/Optional\[PropertyOperator\] = \("[A-Za-z_]*"\)/Optional[PropertyOperator] = PropertyOperator(\1)/g' posthog/schema.py
fi
