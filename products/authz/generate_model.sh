#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
go run github.com/openfga/cli/cmd/fga@v0.8.1 model transform --file products/authz/model.fga --output-format json | python3 -m json.tool > products/authz/openfga_model.json
