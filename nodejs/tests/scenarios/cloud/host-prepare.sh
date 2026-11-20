#!/usr/bin/env bash
set -Eeuo pipefail

export HOME="${HOME:-/root}"
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
prefix="s3://${SCENARIO_EVIDENCE_BUCKET}/runs/${SCENARIO_RUN_ID}"
root=${SCENARIO_HOST_ROOT:-/opt/scenario}
input=$root/input
export XDG_CACHE_HOME=$root/cache
log=$root/prepare.log
exec >"$log" 2>&1
trap 'aws s3 cp --only-show-errors "$log" "$prefix/host/prepare.log" || true' EXIT

cluster=$(aws rds describe-db-clusters --db-cluster-identifier "scn-${SCENARIO_RUN_ID}" --query 'DBClusters[0]' --output json)
endpoint=$(jq -r .Endpoint <<<"$cluster")
secret=$(jq -r .MasterUserSecret.SecretArn <<<"$cluster")
credentials=$(aws secretsmanager get-secret-value --secret-id "$secret" --query SecretString --output text)
user=$(jq -r '.username | @uri' <<<"$credentials")
password=$(jq -r '.password | @uri' <<<"$credentials")
url="postgres://${user}:${password}@${endpoint}:5432/cyclotron_node"
tls="sslmode=verify-full&sslrootcert=$root/rds-ca.pem"
export CYCLOTRON_NODE_DATABASE_URL="${url}?uselibpqcompat=true&${tls}"

sqlx migrate run -D "${url}?${tls}" --source "$repo/rust/cyclotron-node-migrations/"
SCENARIO_RUN_MANIFEST="$input/manifest.json" pnpm --dir "$repo/nodejs" exec tsx tests/scenarios/main.ts seed-backlog --profile "$input/runner-profile.yaml"
