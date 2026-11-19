#!/usr/bin/env bash
set -Eeuo pipefail

AWS_CLI_VERSION=2.22.0
AWS_CLI_SHA256=f315aa564190a12ae05a05bd8ab7b0645dd4a1ad71ce9e47dae4ff3dfeee8ceb
RUSTUP_VERSION=1.29.3
RUSTUP_INIT_SHA256=b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55
PNPM_VERSION=11.28.5
PNPM_SHA256=1ef4e447a68713656064f3f174c0f44719960a043a3fe2299169d08cf1dbf8ee
RUST_TOOLCHAIN=1.91.1
SQLX_CLI_VERSION=0.8.0
UV_VERSION=0.13.4
GO_VERSION=1.26.10
GO_SHA256=ccfe7ae822d2c2f41f4fe7c956199967a4dac22d0ee0d2b2bfdb440aab3b20c5
RDS_CA_URL=https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
RDS_CA_SHA256=90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b

export HOME="${HOME:-/root}"
export DEBIAN_FRONTEND=noninteractive
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
prefix="s3://${SCENARIO_EVIDENCE_BUCKET}/runs/${SCENARIO_RUN_ID}"
root=${SCENARIO_HOST_ROOT:-/opt/scenario}
input=$root/input
log=${SCENARIO_BOOTSTRAP_LOG:-/var/log/scenario-bootstrap.log}
hosts_file=${SCENARIO_HOSTS_FILE:-/etc/hosts}
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
    apt-get install -y -q brotli build-essential ca-certificates curl docker-compose-v2 docker.io git jq libxml2-dev libxmlsec1-dev libxmlsec1-openssl pkg-config postgresql-client protobuf-compiler python3 unzip xz-utils
    if aws --version 2>/dev/null | grep -q "^aws-cli/${AWS_CLI_VERSION} "; then
        return
    fi
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWS_CLI_VERSION}.zip" -o /tmp/awscliv2.zip
    echo "${AWS_CLI_SHA256}  /tmp/awscliv2.zip" | sha256sum --check --strict
    unzip -q /tmp/awscliv2.zip -d /tmp
    /tmp/aws/install --update
}

add_service_hosts() {
    local line
    line=$(sed -n 's/^POSTHOG_HOSTS="\(.*\)"$/\1/p' "$repo/.flox/env/on-activate.sh")
    [ -n "$line" ]
    grep -qxF "$line" "$hosts_file" || printf '%s\n' "$line" >>"$hosts_file"
}

verify_inputs() {
    mkdir -p "$input"
    aws s3 cp --recursive --only-show-errors "$prefix/input/" "$input/"
    [ "$(jq -r .runId "$input/manifest.json")" = "$SCENARIO_RUN_ID" ]
    jq -r '.inputs | to_entries[] | "\(.value)  \(.key)"' "$input/manifest.json" >"$input/SHA256SUMS"
    (cd "$input" && sha256sum --check --strict SHA256SUMS)
}

install_node_and_pnpm() {
    local version
    version=$(cat "$repo/.nvmrc")
    curl -fsSL "https://nodejs.org/dist/${version}/node-${version}-linux-x64.tar.xz" -o "/tmp/node-${version}-linux-x64.tar.xz"
    curl -fsSL "https://nodejs.org/dist/${version}/SHASUMS256.txt" | grep " node-${version}-linux-x64.tar.xz\$" >/tmp/node.sha256
    (cd /tmp && sha256sum --check --strict node.sha256)
    tar -xJf "/tmp/node-${version}-linux-x64.tar.xz" -C /usr/local --strip-components 1
    [ "$(jq -r .packageManager "$repo/package.json")" = "pnpm@${PNPM_VERSION}" ]
    curl -fsSL "https://registry.npmjs.org/pnpm/-/pnpm-${PNPM_VERSION}.tgz" -o /tmp/pnpm.tgz
    echo "${PNPM_SHA256}  /tmp/pnpm.tgz" | sha256sum --check --strict
    mkdir -p /usr/local/lib/pnpm
    tar -xzf /tmp/pnpm.tgz -C /usr/local/lib/pnpm --strip-components 1
    ln -sf /usr/local/lib/pnpm/bin/pnpm.mjs /usr/local/bin/pnpm
}

install_sqlx_cli() {
    curl -fsSL "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init" -o /tmp/rustup-init
    echo "${RUSTUP_INIT_SHA256}  /tmp/rustup-init" | sha256sum --check --strict
    chmod +x /tmp/rustup-init
    /tmp/rustup-init -y --profile minimal --default-toolchain "$RUST_TOOLCHAIN"
    "$HOME/.cargo/bin/cargo" install sqlx-cli --version "$SQLX_CLI_VERSION" --features postgres,rustls --no-default-features --locked --root /usr/local
}

install_uv_and_python() {
    local archive=uv-x86_64-unknown-linux-gnu.tar.gz
    curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${archive}" -o "/tmp/${archive}"
    curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${archive}.sha256" -o "/tmp/${archive}.sha256"
    (cd /tmp && sha256sum --check --strict "${archive}.sha256")
    tar -xzf "/tmp/${archive}" -C /usr/local/bin --strip-components 1
    (cd "$repo" && uv sync --frozen)
}

install_phrocs() {
    curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -o /tmp/go.tar.gz
    echo "${GO_SHA256}  /tmp/go.tar.gz" | sha256sum --check --strict
    tar -xzf /tmp/go.tar.gz -C /usr/local
    (cd "$repo/tools/phrocs" && GOTOOLCHAIN=local /usr/local/go/bin/go build -o /usr/local/bin/phrocs .)
}

install_workspace() {
    pnpm --dir "$repo" install --frozen-lockfile
    (cd "$repo" && PATH="$HOME/.cargo/bin:$PATH" bin/turbo --filter=@posthog/nodejs prepare)
}

install_rds_ca() {
    curl -fsSL "$RDS_CA_URL" -o /tmp/rds-ca.pem
    echo "${RDS_CA_SHA256}  /tmp/rds-ca.pem" | sha256sum --check --strict
    install -m 0644 /tmp/rds-ca.pem "$root/rds-ca.pem"
}

start_poolers() {
    pnpm --dir "$repo/nodejs" exec tsx tests/scenarios/cloud/host-pooler.ts "$input/cloud-profile.yaml"
}

check_ready() {
    node --version
    pnpm --version
    sqlx --version
    "$repo/bin/hogli" --help >/dev/null
    phrocs --version >/dev/null
    docker info >/dev/null
    aws sts get-caller-identity >/dev/null
}

trap poweroff ERR
install_packages_and_aws_cli
trap report_failure ERR
add_service_hosts
verify_inputs
install_node_and_pnpm
install_sqlx_cli
install_uv_and_python
install_phrocs
install_rds_ca
install_workspace
start_poolers
check_ready
mark ready
