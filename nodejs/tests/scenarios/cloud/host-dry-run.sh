#!/usr/bin/env bash
# Runs the run host's scripts in a clean amd64 Ubuntu 24.04 container, in the order a real host runs them:
# host-bootstrap.sh, then host-prepare.sh, then host-run-card.sh. Downloads, checksums and builds are real.
# Stand-ins replace what only a real host has: S3, the instance role, ECR, the Docker daemon and the Aurora
# cluster (a Postgres container with TLS). Each stand-in logs its calls to <work dir>/stand-ins.log.
#
# Usage: host-dry-run.sh <input dir> <work dir>
#   <input dir> holds a run's manifest.json and the inputs it lists, as the controller uploads them.
#   Docker on the machine needs amd64 emulation when it is not amd64 itself.
set -Eeuo pipefail

input=$(cd "$1" && pwd)
work=$(mkdir -p "$2" && cd "$2" && pwd)
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
run_id=$(jq -r .runId "$input/manifest.json")
engine=$(sed -n 's/^engineVersion: "\([0-9]*\)\..*/\1/p' "$input/cloud-profile.yaml")
name=scenario-dry-run-$$
card_seconds=${SCENARIO_DRY_RUN_CARD_SECONDS:-900}

cleanup() { docker rm -f "$name-host" "$name-db" >/dev/null 2>&1 || true; }
trap cleanup EXIT

mkdir -p "$work/stand-ins" "$work/bucket/runs/$run_id/input"
cp "$input"/* "$work/bucket/runs/$run_id/input/"
git -C "$repo" archive --format tar HEAD >"$work/checkout.tar"

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
        echo '{"Endpoint":"127.0.0.1","Port":5432,"MasterUserSecret":{"SecretArn":"arn:aws:secretsmanager:us-east-1:000000000000:secret:dry-run"}}' ;;
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
case "${1:-}" in
    info | pull) ;;
    login) cat >/dev/null ;;
    run)
        name=$(sed -n 's/.* --name \([^ ]*\) .*/\1/p' <<<" $* ")
        mount=$(sed -n 's/.* -v \([^:]*\):.*/\1/p' <<<" $* ")
        command -v pgbouncer >/dev/null || apt-get install -y -q pgbouncer >/dev/null
        mkdir -p "/dry-run/pooler/$name"
        cp "$mount"/* "/dry-run/pooler/$name/"
        sed -i "s#^auth_file = .*#auth_file = /dry-run/pooler/$name/userlist.txt#" "/dry-run/pooler/$name/pgbouncer.ini"
        chown -R nobody "/dry-run/pooler/$name"
        setsid pgbouncer -u nobody "/dry-run/pooler/$name/pgbouncer.ini" >"/dry-run/pooler/$name.log" 2>&1 &
        echo "$name" ;;
    logs) tail -n "$3" "/dry-run/pooler/$4.log" ;;
    *)
        echo "dry run: no Docker daemon for docker $*" >&2
        exit 1 ;;
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
cd /opt/posthog
export AWS_REGION=us-east-1 SCENARIO_RUN_ID="$RUN_ID" SCENARIO_EVIDENCE_BUCKET=dry-run
step "host-bootstrap.sh"
bash nodejs/tests/scenarios/cloud/host-bootstrap.sh || { echo "host-bootstrap.sh exited $?"; exit 1; }
step "host-prepare.sh"
bash nodejs/tests/scenarios/cloud/host-prepare.sh
code=$?
cat /opt/scenario/prepare.log
[ "$code" = 0 ] || { echo "host-prepare.sh exited $code"; exit 1; }
step "host-run-card.sh, stopped after $CARD_SECONDS s"
timeout --signal TERM "$CARD_SECONDS" bash nodejs/tests/scenarios/cloud/host-run-card.sh
echo "host-run-card.sh exited $?"
cat /opt/scenario/evidence/card.log
cat "/dry-run/bucket/runs/$RUN_ID/host/done"
EOF

password='dry:Run#1?&%x'
docker run -d --name "$name-db" \
    -e POSTGRES_USER=posthog -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB=cyclotron_node \
    "postgres:${engine:-16}" \
    -c ssl=on -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key \
    >/dev/null
docker run --name "$name-host" --platform linux/amd64 --network "container:$name-db" \
    -e RUN_ID="$run_id" -e CARD_SECONDS="$card_seconds" -e DRY_RUN_DB_PASSWORD="$password" \
    -v "$work:/dry-run" ubuntu:24.04 bash /dry-run/host.sh 2>&1 | tee "$work/host.log"
