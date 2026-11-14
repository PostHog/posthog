#!/usr/bin/env bash
set -Eeuo pipefail

AWS_CLI_VERSION=2.22.0
AWS_CLI_SHA256=f315aa564190a12ae05a05bd8ab7b0645dd4a1ad71ce9e47dae4ff3dfeee8ceb
RUSTUP_VERSION=1.29.3
RUSTUP_INIT_SHA256=b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55
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
    echo "${AWS_CLI_SHA256}  /tmp/awscliv2.zip" | sha256sum --check --strict
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
    npm install --global "pnpm@${pnpm_version}"
}

install_sqlx_cli() {
    curl -fsSL "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init" -o /tmp/rustup-init
    echo "${RUSTUP_INIT_SHA256}  /tmp/rustup-init" | sha256sum --check --strict
    chmod +x /tmp/rustup-init
    /tmp/rustup-init -y --profile minimal --default-toolchain "$RUST_TOOLCHAIN"
    "$HOME/.cargo/bin/cargo" install sqlx-cli --version "$SQLX_CLI_VERSION" --features postgres,rustls --no-default-features --locked --root /usr/local
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
