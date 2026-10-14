#!/usr/bin/env bash
# Builds generated/model.fga from products/authz/model/, converts it to generated/openfga_model.json, checks the model rules,
# and runs the OpenFGA tests in products/authz/model/.
# Pass --force to overwrite changes made to generated/model.fga by hand.
set -euo pipefail
cd "$(dirname "$0")/../.."
fga=(go run github.com/openfga/cli/cmd/fga@v0.8.1)
python3 -m products.authz.backend.logic.model_builder build "$@"
json_model="$(mktemp)"
trap 'rm -f "$json_model"' EXIT
"${fga[@]}" model transform --file products/authz/generated/model.fga --output-format json | python3 -m json.tool >"$json_model"
cat "$json_model" >products/authz/generated/openfga_model.json
python3 -m products.authz.backend.logic.model_builder check
# The test files load generated/model.fga and the shared fixtures through relative paths.
"${fga[@]}" model test --allow-external-files --tests products/authz/model/core.fga.yaml
"${fga[@]}" model test --allow-external-files --tests 'products/authz/model/resources/*.fga.yaml'
