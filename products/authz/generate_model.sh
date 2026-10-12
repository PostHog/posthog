#!/usr/bin/env bash
# Builds model.fga from products/authz/model/, converts it to openfga_model.json, checks the model rules,
# and runs the OpenFGA tests in products/authz/model/.
# Pass --force to overwrite changes made to model.fga by hand.
set -euo pipefail
cd "$(dirname "$0")/../.."
fga=(go run github.com/openfga/cli/cmd/fga@v0.8.1)
python3 -m products.authz.backend.logic.model_builder build "$@"
json_model="$(mktemp)"
trap 'rm -f "$json_model"' EXIT
"${fga[@]}" model transform --file products/authz/model.fga --output-format json | python3 -m json.tool >"$json_model"
cat "$json_model" >products/authz/openfga_model.json
python3 -m products.authz.backend.logic.model_builder check
# The test files load model.fga and the shared fixtures from parent directories.
"${fga[@]}" model test --allow-external-files --tests products/authz/model/core.fga.yaml
"${fga[@]}" model test --allow-external-files --tests 'products/authz/model/resources/*.fga.yaml'
