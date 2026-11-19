#!/usr/bin/env bash
set -Eeuo pipefail

if [ $# -ne 2 ]; then
    echo "Usage: $0 <input dir with a run's manifest.json and its inputs> <work dir>" >&2
    exit 2
fi

input=$(cd "$1" && pwd)
work=$(mkdir -p "$2" && cd "$2" && pwd)
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
run_id=$(jq -r .runId "$input/manifest.json")
engine=$(sed -n 's/^engineVersion: "\([0-9]*\)\..*/\1/p' "$input/cloud-profile.yaml")
name=scenario-dry-run-$$
bootstrap=$work/host-bootstrap.head.sh
git -C "$repo" show HEAD:nodejs/tests/scenarios/cloud/host-bootstrap.sh >"$bootstrap"
card_seconds=${SCENARIO_DRY_RUN_CARD_SECONDS:-900}
source <(grep -E '^[A-Z0-9_]+=' "$bootstrap")
node_version=$(git -C "$repo" show HEAD:.nvmrc)

check_amd64_downloads() {
    local dir=$work/amd64
    mkdir -p "$dir"
    cd "$dir"
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWS_CLI_VERSION}.zip" -o awscli.zip
    echo "${AWS_CLI_SHA256}  awscli.zip" | sha256sum --check --strict
    unzip -l awscli.zip aws/install | grep aws/install >/dev/null
    curl -fsSL "https://nodejs.org/dist/${node_version}/node-${node_version}-linux-x64.tar.xz" -o "node-${node_version}-linux-x64.tar.xz"
    curl -fsSL "https://nodejs.org/dist/${node_version}/SHASUMS256.txt" | grep " node-${node_version}-linux-x64.tar.xz\$" | sha256sum --check --strict
    tar -tJf "node-${node_version}-linux-x64.tar.xz" | grep "^node-${node_version}-linux-x64/bin/node\$" >/dev/null
    curl -fsSL "https://registry.npmjs.org/pnpm/-/pnpm-${PNPM_VERSION}.tgz" -o pnpm.tgz
    echo "${PNPM_SHA256}  pnpm.tgz" | sha256sum --check --strict
    tar -tzf pnpm.tgz | grep -c -E '^package/(bin|dist)/pnpm.mjs$' | grep '^2$' >/dev/null
    curl -fsSL "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init" -o rustup-init
    echo "${RUSTUP_INIT_SHA256}  rustup-init" | sha256sum --check --strict
    curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" -o uv-x86_64-unknown-linux-gnu.tar.gz
    curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz.sha256" | sha256sum --check --strict
    tar -tzf uv-x86_64-unknown-linux-gnu.tar.gz | grep '^uv-x86_64-unknown-linux-gnu/uv$' >/dev/null
    curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -o go.tar.gz
    echo "${GO_SHA256}  go.tar.gz" | sha256sum --check --strict
    tar -tzf go.tar.gz | grep '^go/bin/go$' >/dev/null
    cd - >/dev/null
}

check_rds_ca() {
    curl -fsSL "$RDS_CA_URL" -o "$work/rds-ca.pem"
    echo "${RDS_CA_SHA256}  $work/rds-ca.pem" | sha256sum --check --strict
}

make_cluster_certificate() {
    local dir=$work/tls
    mkdir -p "$dir"
    openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj '/CN=scenario dry-run CA' \
        -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign,cRLSign \
        -keyout "$dir/ca.key" -out "$dir/ca.pem" 2>/dev/null
    openssl req -newkey rsa:2048 -nodes -subj /CN=cluster -keyout "$dir/server.key" -out "$dir/server.csr" 2>/dev/null
    openssl x509 -req -in "$dir/server.csr" -CA "$dir/ca.pem" -CAkey "$dir/ca.key" -CAcreateserial -days 2 \
        -extfile <(printf 'subjectAltName=DNS:cluster\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n') \
        -out "$dir/server.crt" 2>/dev/null
}

sha256_of() { curl -fsSL "$1" | sha256sum | cut -d' ' -f1; }

arm64_bootstrap() {
    sed \
        -e "s#awscli-exe-linux-x86_64-#awscli-exe-linux-aarch64-#" \
        -e "s#x86_64-unknown-linux-gnu#aarch64-unknown-linux-gnu#g" \
        -e "s#linux-x64#linux-arm64#g" \
        -e "s#linux-amd64#linux-arm64#g" \
        -e "s#^AWS_CLI_SHA256=.*#AWS_CLI_SHA256=$(sha256_of "https://awscli.amazonaws.com/awscli-exe-linux-aarch64-${AWS_CLI_VERSION}.zip")#" \
        -e "s#^RUSTUP_INIT_SHA256=.*#RUSTUP_INIT_SHA256=$(sha256_of "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/aarch64-unknown-linux-gnu/rustup-init")#" \
        -e "s#^GO_SHA256=.*#GO_SHA256=$(sha256_of "https://go.dev/dl/go${GO_VERSION}.linux-arm64.tar.gz")#" \
        "$bootstrap"
}

cleanup() {
    docker rm -f "$name-host" "$name-db" >/dev/null 2>&1 || true
    docker volume rm "$name-docker" >/dev/null 2>&1 || true
    docker network rm "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

mkdir -p "$work/stand-ins" "$work/bucket/runs/$run_id/input"
cp "$input"/* "$work/bucket/runs/$run_id/input/"
git -C "$repo" archive --format tar HEAD >"$work/checkout.tar"
echo "=== checking the pinned RDS CA bundle"
check_rds_ca
echo "RDS CA bundle matches its pin"
make_cluster_certificate
case $(docker info --format '{{.Architecture}}') in
    x86_64)
        platform=linux/amd64
        cp "$bootstrap" "$work/host-bootstrap.sh"
        ;;
    aarch64)
        platform=linux/arm64
        echo "=== checking the pinned amd64 downloads"
        check_amd64_downloads
        echo "amd64 downloads match their pins"
        arm64_bootstrap >"$work/host-bootstrap.sh"
        ;;
    *) echo "No dry run on $(docker info --format '{{.Architecture}}')" >&2; exit 1 ;;
esac
sed -i -e "s#^RDS_CA_URL=.*#RDS_CA_URL=file:///dry-run/tls/ca.pem#" \
    -e "s#^RDS_CA_SHA256=.*#RDS_CA_SHA256=$(sha256sum "$work/tls/ca.pem" | cut -d' ' -f1)#" \
    "$work/host-bootstrap.sh"

cat >"$work/stand-ins/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "aws $*" >>/dry-run/stand-ins.log
bucket() { sed "s#^s3://[^/]*#/dry-run/bucket#" <<<"$1"; }
case "${1:-} ${2:-}" in
    "--version ")
        exec /usr/local/bin/aws --version ;;
    "s3 cp")
        shift 2
        paths=()
        for arg in "$@"; do case "$arg" in --*) ;; *) paths+=("$arg") ;; esac; done
        src=$(bucket "${paths[0]}")
        dst=$(bucket "${paths[1]}")
        case " $* " in
            *" --recursive "*) mkdir -p "$dst" && cp -R "$src/." "$dst/" ;;
            *) mkdir -p "$(dirname "$dst")" && if [ "$src" = - ]; then cat >"$dst"; else cp "$src" "$dst"; fi ;;
        esac ;;
    "sts get-caller-identity")
        echo '{"Account":"000000000000","Arn":"arn:aws:sts::000000000000:assumed-role/dry-run/host"}' ;;
    "rds describe-db-clusters")
        jq -cn --arg endpoint "${DRY_RUN_ENDPOINT:-cluster}" '{Endpoint:$endpoint,Port:5432,MasterUserSecret:{SecretArn:"arn:aws:secretsmanager:us-east-1:000000000000:secret:dry-run"}}' ;;
    "secretsmanager get-secret-value")
        jq -cn --arg password "$DRY_RUN_DB_PASSWORD" '{username:"posthog",password:$password}' ;;
    "ecr get-login-password")
        echo dry-run-token ;;
    *)
        echo "dry run: no stand-in for aws $*" >&2
        exit 1 ;;
esac
EOF

cat >"$work/stand-ins/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "docker $*" >>/dry-run/stand-ins.log
real=/usr/bin/docker
daemon() {
    "$real" info >/dev/null 2>&1 && return
    if [ -f /sys/fs/cgroup/cgroup.controllers ] && [ ! -d /sys/fs/cgroup/init ]; then
        mkdir /sys/fs/cgroup/init
        xargs -rn1 </sys/fs/cgroup/cgroup.procs >/sys/fs/cgroup/init/cgroup.procs 2>/dev/null || true
        sed -e 's/ / +/g' -e 's/^/+/' </sys/fs/cgroup/cgroup.controllers >/sys/fs/cgroup/cgroup.subtree_control
    fi
    (setsid dockerd >>/dry-run/dockerd.log 2>&1 &)
    for _ in $(seq 60); do "$real" info >/dev/null 2>&1 && return; sleep 1; done
    echo "dry run: dockerd did not start; see dockerd.log" >&2
    exit 1
}
pooler() {
    local name mount
    name=$(sed -n 's/.* --name \([^ ]*\) .*/\1/p' <<<" $* ")
    mount=$(sed -n 's/.* -v \([^:]*\):.*/\1/p' <<<" $* ")
    command -v pgbouncer >/dev/null || apt-get install -y -q pgbouncer >/dev/null
    mkdir -p "/dry-run/pooler/$name"
    cp "$mount"/* "/dry-run/pooler/$name/"
    sed -i "s#^auth_file = .*#auth_file = /dry-run/pooler/$name/userlist.txt#" "/dry-run/pooler/$name/pgbouncer.ini"
    chown -R nobody "/dry-run/pooler/$name"
    setsid pgbouncer -u nobody "/dry-run/pooler/$name/pgbouncer.ini" >"/dry-run/pooler/$name.log" 2>&1 &
    echo "$name"
}
case " $* " in
    " login "*.dkr.ecr.*) cat >/dev/null ;;
    " pull "*.dkr.ecr.*) ;;
    " run "*" --entrypoint pgbouncer "*) pooler "$@" ;;
    " logs "*" scenario-pooler-"*) tail -n "$3" "/dry-run/pooler/$4.log" ;;
    *) daemon && exec "$real" "$@" ;;
esac
EOF

cat >"$work/stand-ins/poweroff" <<'EOF'
#!/usr/bin/env bash
echo "poweroff" >>/dry-run/stand-ins.log
EOF

cat >"$work/host.sh" <<'EOF'
#!/usr/bin/env bash
set -uo pipefail
step() { printf '\n=== %s %s\n' "$(date -u +%H:%M:%SZ)" "$1"; }
step "image setup: git, which the host image ships and a container image does not"
apt-get update -q >/dev/null && apt-get install -y -q git >/dev/null
install -m 0755 /dry-run/stand-ins/aws /dry-run/stand-ins/docker /dry-run/stand-ins/poweroff /usr/local/sbin/
mkdir -p /opt/posthog && tar -xf /dry-run/checkout.tar -C /opt/posthog
echo "running the bootstrap with the dry run's CA and, on arm64, the arm64 build of each pinned download"
cp /dry-run/host-bootstrap.sh /opt/posthog/nodejs/tests/scenarios/cloud/host-bootstrap.sh
cd /opt/posthog
export AWS_REGION=us-east-1 SCENARIO_RUN_ID="$RUN_ID" SCENARIO_EVIDENCE_BUCKET=dry-run
step "the host resolves no stack service name before the bootstrap, as a fresh run host"
if getent hosts db; then
    echo "db resolves before the bootstrap, so this dry run would hide a missing hosts entry"
    exit 1
fi
step "host-bootstrap.sh"
bash nodejs/tests/scenarios/cloud/host-bootstrap.sh || { echo "host-bootstrap.sh exited $?"; exit 1; }
getent hosts db || { echo "db does not resolve after the bootstrap"; exit 1; }
step "host-prepare.sh"
bash nodejs/tests/scenarios/cloud/host-prepare.sh
code=$?
cat /opt/scenario/prepare.log
[ "$code" = 0 ] || { echo "host-prepare.sh exited $code"; exit 1; }
cp /opt/scenario/prepare.log /dry-run/prepare.log
backlog=/opt/scenario/cache/posthog-scenarios/backlog.json
cp "$backlog" /dry-run/backlog.json
refused() {
    if DRY_RUN_ENDPOINT=not-in-certificate PATH="$2:$PATH" bash nodejs/tests/scenarios/cloud/host-prepare.sh; then
        echo "host-prepare.sh connected over $1 to a name the certificate lacks"; exit 1
    fi
    cp /opt/scenario/prepare.log "/dry-run/prepare-refused-$1.log"
    grep -E "$3" /opt/scenario/prepare.log || { cat /opt/scenario/prepare.log; echo "host-prepare.sh failed over $1 for another reason"; exit 1; }
}
step "host-prepare.sh refuses a cluster name its certificate lacks, for sqlx and then for Node"
mkdir -p /dry-run/skip-sqlx && printf '#!/bin/sh\nexit 0\n' >/dry-run/skip-sqlx/sqlx && chmod +x /dry-run/skip-sqlx/sqlx
refused sqlx /nonexistent NotValidForName
refused node /dry-run/skip-sqlx altnames
cp /dry-run/backlog.json "$backlog"
cp /dry-run/prepare.log /opt/scenario/prepare.log
cp /dry-run/prepare.log "/dry-run/bucket/runs/$RUN_ID/host/prepare.log"
step "host-run-card.sh, stopped after $CARD_SECONDS s"
rm -rf "/dry-run/bucket/runs/$RUN_ID/evidence" "/dry-run/bucket/runs/$RUN_ID/host/done"
timeout --signal TERM --kill-after 60 "$CARD_SECONDS" bash nodejs/tests/scenarios/cloud/host-run-card.sh
stopped=$?
cat /opt/scenario/evidence/card.log
done=/dry-run/bucket/runs/$RUN_ID/host/done
cat "$done" || { echo "The card wrote no done marker."; exit 1; }
[ "$(jq -r .uploaded "$done")" = true ] || { echo "The card did not upload its evidence."; exit 1; }
if [ "$stopped" = 124 ]; then
    [ -d "/dry-run/bucket/runs/$RUN_ID/evidence/run/$RUN_ID" ] || {
        echo "The card was stopped after $CARD_SECONDS s before its run started."
        exit 1
    }
    echo "The card was still running after $CARD_SECONDS s, as intended."
    exit 0
fi
code=$(jq -r .exitCode "$done")
echo "The card ended with exit $code before the stop."
exit "$code"
EOF

password='dry:Run#1?&%x'
upstream_resolver() {
    local file
    for file in /run/systemd/resolve/resolv.conf /etc/resolv.conf; do
        [ -r "$file" ] || continue
        awk '$1 == "nameserver" && $2 !~ /^127\./ && $2 != "::1" { print $2; found = 1; exit } END { exit !found }' "$file" && return 0
    done
    echo "No resolver outside this machine in /run/systemd/resolve/resolv.conf or /etc/resolv.conf; the host container needs one to resolve as a run host does" >&2
    return 1
}
upstream=$(upstream_resolver)
docker network create "$name" >/dev/null
docker run -d --name "$name-db" --network "$name" --network-alias cluster --network-alias not-in-certificate \
    -e POSTGRES_USER=posthog -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB=cyclotron_node \
    -v "$work/tls:/tls:ro" --entrypoint bash "postgres:${engine:-16}" -c \
    'install -o postgres -m 0600 /tls/server.crt /tls/server.key /var/lib/postgresql/ && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/var/lib/postgresql/server.crt -c ssl_key_file=/var/lib/postgresql/server.key' \
    >/dev/null
docker run --name "$name-host" --platform "$platform" --network "$name" --dns "$upstream" --privileged -v "$name-docker:/var/lib/docker" \
    -e RUN_ID="$run_id" -e CARD_SECONDS="$card_seconds" -e DRY_RUN_DB_PASSWORD="$password" \
    -v "$work:/dry-run" ubuntu:24.04 bash /dry-run/host.sh 2>&1 | tee "$work/host.log"
