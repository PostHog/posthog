#!/usr/bin/env bash
set -Eeuo pipefail

export HOME="${HOME:-/root}"
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
prefix="s3://${SCENARIO_EVIDENCE_BUCKET}/runs/${SCENARIO_RUN_ID}"
root=${SCENARIO_HOST_ROOT:-/opt/scenario}
input=$root/input
log=$root/prepare.log
exec >"$log" 2>&1
trap 'aws s3 cp --only-show-errors "$log" "$prefix/host/prepare.log" || true' EXIT

cluster=$(aws rds describe-db-clusters --db-cluster-identifier "scn-${SCENARIO_RUN_ID}" --query 'DBClusters[0]' --output json)
endpoint=$(jq -r .Endpoint <<<"$cluster")
secret=$(jq -r .MasterUserSecret.SecretArn <<<"$cluster")
credentials=$(aws secretsmanager get-secret-value --secret-id "$secret" --query SecretString --output text)
user=$(jq -r '.username | @uri' <<<"$credentials")
password=$(jq -r '.password | @uri' <<<"$credentials")
export CYCLOTRON_NODE_DATABASE_URL="postgres://${user}:${password}@${endpoint}:5432/cyclotron_node?sslmode=require"

sqlx migrate run -D "$CYCLOTRON_NODE_DATABASE_URL" --source "$repo/rust/cyclotron-node-migrations/"
SCENARIO_RUN_MANIFEST="$input/manifest.json" pnpm --dir "$repo/nodejs" exec tsx tests/scenarios/main.ts seed-backlog --profile "$input/runner-profile.yaml"
