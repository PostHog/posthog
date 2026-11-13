#!/usr/bin/env bash
set -Eeuo pipefail

AWS_CLI_VERSION=2.22.0
RUST_TOOLCHAIN=1.91.1
SQLX_CLI_VERSION=0.8.0

export HOME="${HOME:-/root}"
export DEBIAN_FRONTEND=noninteractive
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
prefix="s3://${SCENARIO_EVIDENCE_BUCKET}/runs/${SCENARIO_RUN_ID}"
input=/opt/scenario/input
log=/var/log/scenario-bootstrap.log
exec > >(tee -a "$log") 2>&1

mark() {
    printf '{"at":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | aws s3 cp - "$prefix/host/$1"
}

report_failure() {
    aws s3 cp "$log" "$prefix/host/bootstrap.log" || true
    mark failed || true
}

install_packages_and_aws_cli() {
    apt-get update -q
    apt-get install -y -q build-essential ca-certificates curl docker-compose-v2 docker.io git jq pkg-config unzip xz-utils
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWS_CLI_VERSION}.zip" -o /tmp/awscliv2.zip
    unzip -q /tmp/awscliv2.zip -d /tmp
    /tmp/aws/install --update
}

verify_inputs() {
    mkdir -p "$input"
    aws s3 cp --recursive --only-show-errors "$prefix/input/" "$input/"
    [ "$(jq -r .runId "$input/manifest.json")" = "$SCENARIO_RUN_ID" ]
    jq -r '.inputs | to_entries[] | "\(.value)  \(.key)"' "$input/manifest.json" >"$input/SHA256SUMS"
    (cd "$input" && sha256sum --check --strict SHA256SUMS)
}

install_node_and_pnpm() {
    local version pnpm_version
    version=$(cat "$repo/.nvmrc")
    curl -fsSL "https://nodejs.org/dist/${version}/node-${version}-linux-x64.tar.xz" -o "/tmp/node-${version}-linux-x64.tar.xz"
    curl -fsSL "https://nodejs.org/dist/${version}/SHASUMS256.txt" | grep " node-${version}-linux-x64.tar.xz\$" >/tmp/node.sha256
    (cd /tmp && sha256sum --check --strict node.sha256)
    tar -xJf "/tmp/node-${version}-linux-x64.tar.xz" -C /usr/local --strip-components 1
    pnpm_version=$(jq -r '.packageManager | sub("^pnpm@"; "")' "$repo/package.json")
    curl -fsSL "https://github.com/pnpm/pnpm/releases/download/v${pnpm_version}/pnpm-linux-x64" -o /usr/local/bin/pnpm
    chmod +x /usr/local/bin/pnpm
}

install_sqlx_cli() {
    curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain "$RUST_TOOLCHAIN"
    "$HOME/.cargo/bin/cargo" install sqlx-cli --version "$SQLX_CLI_VERSION" --features postgres --no-default-features --locked --root /usr/local
}

check_ready() {
    node --version
    pnpm --version
    sqlx --version
    docker info >/dev/null
    aws sts get-caller-identity >/dev/null
}

install_packages_and_aws_cli
trap report_failure ERR
verify_inputs
install_node_and_pnpm
install_sqlx_cli
pnpm --dir "$repo" install --frozen-lockfile
check_ready
mark ready
