#!/usr/bin/env bash
#
# Cloud-init user data script for cloud sandboxes.
#
# This script runs ONCE at first boot on a STOCK Ubuntu 24.04 AMI.
# It's templated by bin/sandbox — placeholders like __SANDBOX_BRANCH__
# are replaced at launch time.
#
# Boot flow (optimised for parallelism):
#   1. Install Tailscale + join network (enables SSH for debugging)
#   2. Write SSH keys + Claude auth
#   3. Detect + format + mount NVMe instance store
#   4. Install base deps (aria2, zstd, git, python3-yaml)
#   5. Background: per-chunk S3 downloads + git clone
#   6. Foreground: Docker repo + install
#   7. Wait for each chunk download, extract immediately (overlap I/O)
#   8. Start Docker
#   9. Wait for git clone, checkout branch
#  10. bin/sandbox create <branch> --no-attach
#
set -euo pipefail
exec > /var/log/sandbox-boot.log 2>&1

SECONDS=0
log() { echo "==> [${SECONDS}s] $*"; }

# Write boot status on exit so the CLI can detect failure quickly.
BOOT_STATUS="failed"
cleanup() {
    log "Boot status: $BOOT_STATUS"
    echo "$BOOT_STATUS" > /var/log/sandbox-boot-status
}
trap cleanup EXIT

# Shared host provisioning helpers (setup_nvme, install_docker_overlay2).
# Inlined at render time by bin/sandbox_cloud.py::_render_template.
__PROVISION_HOST__

log "Cloud sandbox boot starting at $(date)"

SANDBOX_BRANCH="__SANDBOX_BRANCH__"
SANDBOX_OWNER="__SANDBOX_OWNER__"
SANDBOX_HOSTNAME="__SANDBOX_HOSTNAME__"
SANDBOX_JETBRAINS="__SANDBOX_JETBRAINS__"
CLAUDE_CREDENTIALS_B64="__CLAUDE_CREDENTIALS_B64__"
CLAUDE_SETTINGS_B64="__CLAUDE_SETTINGS_B64__"
CLAUDE_JSON_B64="__CLAUDE_JSON_B64__"
S3_ARCHIVE_MANIFEST_B64="__S3_ARCHIVE_MANIFEST_B64__"
TAILSCALE_AUTH_KEY_B64="__TAILSCALE_AUTH_KEY_B64__"
SSH_AUTHORIZED_KEYS_B64="__SSH_AUTHORIZED_KEYS_B64__"

if [ -n "$S3_ARCHIVE_MANIFEST_B64" ]; then
    echo "$S3_ARCHIVE_MANIFEST_B64" | base64 -d > /tmp/cache-manifest.json
fi
TAILSCALE_AUTH_KEY=""
if [ -n "$TAILSCALE_AUTH_KEY_B64" ]; then
    TAILSCALE_AUTH_KEY=$(echo "$TAILSCALE_AUTH_KEY_B64" | base64 -d)
fi
SSH_AUTHORIZED_KEYS=""
if [ -n "$SSH_AUTHORIZED_KEYS_B64" ]; then
    SSH_AUTHORIZED_KEYS=$(echo "$SSH_AUTHORIZED_KEYS_B64" | base64 -d)
fi

REPO_DIR="/home/ubuntu/posthog"

log "Installing Tailscale..."
mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg \
    | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list \
    | tee /etc/apt/sources.list.d/tailscale.list >/dev/null
apt-get update -qq
apt-get install -y -qq tailscale
systemctl enable tailscaled

log "Joining Tailscale network..."
tailscale up \
    --authkey="$TAILSCALE_AUTH_KEY" \
    --hostname="$SANDBOX_HOSTNAME" \
    --ssh
log "Tailscale joined as $SANDBOX_HOSTNAME"

# Kick off the Tailscale HTTPS cert request in the background RIGHT NOW. The
# ACME roundtrip takes ~30s, and we need the cert before `bin/sandbox create`
# can start (SANDBOX_JS_URL is baked into the JS bundles during container
# build). If we run it inline later, those 30s sit on the critical path. By
# backgrounding it alongside docker install + archive extract + git clone,
# the cost disappears behind work we're doing anyway.
CERT_PID=""
CERT_STATUS_FILE=/tmp/sandbox-cert-status
CERT_LOG=/tmp/sandbox-cert.log
FQDN=""
TAILNET_SUFFIX=$(
    tailscale status --json 2>/dev/null \
        | python3 -c "import json,sys; print(json.load(sys.stdin).get('MagicDNSSuffix',''))" \
        2>/dev/null || true
)
if [ -n "$TAILNET_SUFFIX" ]; then
    FQDN="${SANDBOX_HOSTNAME}.${TAILNET_SUFFIX}"
    log "Requesting Tailscale HTTPS cert for $FQDN in background..."
    rm -f "$CERT_STATUS_FILE"
    (
        # Run from /tmp so the cert files don't litter a random cwd. The cert
        # is also cached inside tailscaled, which is what `tailscale serve`
        # actually reads from — the files here are just a side effect.
        cd /tmp
        if tailscale cert "$FQDN" >"$CERT_LOG" 2>&1; then
            echo "ok" > "$CERT_STATUS_FILE"
        else
            echo "fail" > "$CERT_STATUS_FILE"
        fi
    ) &
    CERT_PID=$!
else
    log "WARNING: could not read tailnet MagicDNSSuffix. Falling back to HTTP."
fi

log "Writing SSH authorized keys..."
UBUNTU_SSH_DIR="/home/ubuntu/.ssh"
mkdir -p "$UBUNTU_SSH_DIR"
echo "$SSH_AUTHORIZED_KEYS" > "$UBUNTU_SSH_DIR/authorized_keys"
# Also write as a .pub file so _ssh_authorized_keys_path() finds them
echo "$SSH_AUTHORIZED_KEYS" > "$UBUNTU_SSH_DIR/cloud.pub"
chmod 700 "$UBUNTU_SSH_DIR"
chmod 600 "$UBUNTU_SSH_DIR/authorized_keys"
chmod 644 "$UBUNTU_SSH_DIR/cloud.pub"
chown -R ubuntu:ubuntu "$UBUNTU_SSH_DIR"

log "Writing Claude Code auth..."
CLAUDE_AUTH_DIR="/home/ubuntu/.claude"
mkdir -p "$CLAUDE_AUTH_DIR"

if [ -n "$CLAUDE_CREDENTIALS_B64" ]; then
    echo "$CLAUDE_CREDENTIALS_B64" | base64 -d > "$CLAUDE_AUTH_DIR/.credentials.json"
fi
if [ -n "$CLAUDE_SETTINGS_B64" ]; then
    echo "$CLAUDE_SETTINGS_B64" | base64 -d > "$CLAUDE_AUTH_DIR/settings.json"
fi

if [ -n "$CLAUDE_JSON_B64" ]; then
    echo "$CLAUDE_JSON_B64" | base64 -d > "/home/ubuntu/.claude.json"
    chown ubuntu:ubuntu "/home/ubuntu/.claude.json"
fi

chown -R ubuntu:ubuntu "$CLAUDE_AUTH_DIR"

# Set up NVMe before Docker so Docker data lands on fast local storage.
log "Setting up NVMe instance store..."
setup_nvme

if [ "$USE_NVME" = true ]; then
    mkdir -p /mnt/nvme/docker
    rm -rf /var/lib/docker
    ln -s /mnt/nvme/docker /var/lib/docker
    log "Symlinked /var/lib/docker -> /mnt/nvme/docker"
fi

# Swap + zswap on NVMe. The instance has 32 GB RAM, which is enough for
# steady state but tight during Rust builds / ClickHouse queries / big TS
# type-checks. zswap compresses pages in RAM before they actually hit disk,
# so hot anon pages get lz4 compression for free and cold pages spill to
# NVMe with no hard cap.
#
# vm.swappiness=180 (kernel 5.8+ allows 0-200) strongly prefers swapping
# anon heap over evicting file cache. The shared pnpm/cargo/uv caches and
# node_modules are our hottest file-cache pages — losing them causes slow
# rebuilds — while anon heap compresses ~2-3x for free in zswap. Keep file
# cache alive, push anon into zswap.
if [ "$USE_NVME" = true ]; then
    log "Setting up 32G swapfile on NVMe..."
    fallocate -l 32G /mnt/nvme/swapfile
    chmod 600 /mnt/nvme/swapfile
    mkswap /mnt/nvme/swapfile >/dev/null
    swapon /mnt/nvme/swapfile
    log "Swap enabled: $(swapon --show=NAME,SIZE --noheadings | tr -s ' ')"

    echo lz4      > /sys/module/zswap/parameters/compressor       || true
    echo zsmalloc > /sys/module/zswap/parameters/zpool            || true
    echo 20       > /sys/module/zswap/parameters/max_pool_percent || true
    echo 1        > /sys/module/zswap/parameters/enabled          || true
    log "zswap: enabled=$(cat /sys/module/zswap/parameters/enabled) compressor=$(cat /sys/module/zswap/parameters/compressor) max_pool_percent=$(cat /sys/module/zswap/parameters/max_pool_percent)"

    # vm.dirty_ratio=40:          writers can accumulate up to 40% of RAM (~13GB
    #                              on a 32GB box) before being throttled. Defaults
    #                              are 20/10. Bursty writers — tar extract of the
    #                              cache archive, cargo output, pnpm unpack —
    #                              benefit from the larger buffer, and on an
    #                              ephemeral store we don't care about the data
    #                              loss window this opens up.
    # vm.vfs_cache_pressure=50:    half the default. Keeps dentry/inode cache
    #                              around longer, which matters for cargo
    #                              rebuilds (walks millions of files) and for
    #                              incremental TS type-checks.
    cat > /etc/sysctl.d/99-sandbox.conf <<'SYSCTL'
vm.swappiness=180
vm.dirty_ratio=40
vm.vfs_cache_pressure=50
SYSCTL
    sysctl --system >/dev/null
else
    log "No NVMe device, skipping swap setup"
fi

log "Installing base dependencies..."
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg zstd git python3-yaml

# Streaming download+extract pipelines. Curl streams raw bytes from S3
# straight into `unzstd | tar`, so extraction writes to disk from the
# first byte. No intermediate file, no "download then extract" serial
# phase.
#
# Rationale:
# - Extract is the bottleneck, not network. The previous run measured
#   ~85 MB/s aggregate tar throughput on /var/lib/docker (millions of
#   small overlay2 files — metadata-bound on ext4, not bandwidth-bound
#   on NVMe). Network was ~260 MiB/s per chunk via aria2 — way faster
#   than extract. So downloading to a file first just parked those
#   bytes on disk waiting.
# - base.tar.zst is ~80% of the payload and it downloads last. With
#   download-then-extract, base extract didn't even START until all
#   5 chunks were fully downloaded (~60s in). Now it starts at t=0.
# - The pipe auto-regulates: when unzstd+tar can't keep up, curl blocks
#   on write, TCP backpressure slows S3. We pull bytes at exactly extract
#   speed, no disk churn.
# - Single-connection curl is slower than 8-connection aria2 on paper
#   (~1 Gbit/s vs ~2 Gbit/s per chunk), but since extract caps us well
#   below either, it doesn't matter. 5 chunks × curl in parallel still
#   saturates the extract pipeline.
#
# Runs concurrently with Docker install (guarded by policy-rc.d) and
# git clone below, so the total critical-path cost collapses to
# max(extract_time, docker_install_time) instead of
# download_time + extract_time.
mkdir -p /var/lib/docker
CHUNK_PIDS=()
stream_start=$SECONDS
if [ -f /tmp/cache-manifest.json ]; then
    log "Starting streaming download+extract pipelines..."
    while IFS=$'\t' read -r name url; do
        (
            set -o pipefail
            for attempt in 1 2 3; do
                echo "==> [${SECONDS}s] Streaming $name (attempt $attempt)..."
                if curl -fsSL --retry 0 "$url" \
                     | tar -C /var/lib/docker -I unzstd -xf -; then
                    echo "==> [${SECONDS}s] Stream-extracted $name"
                    exit 0
                fi
                [ "$attempt" = 3 ] && {
                    echo "==> [${SECONDS}s] FAILED $name after 3 attempts" >&2
                    exit 1
                }
                sleep 5
            done
        ) &
        CHUNK_PIDS+=($!)
    done < <(python3 -c "
import json
for e in json.load(open('/tmp/cache-manifest.json')):
    print(e['name'] + '\t' + e['url'])
")
    log "Started ${#CHUNK_PIDS[@]} streaming pipelines"
else
    log "WARNING: No cache manifest provided, Docker starts with no cached images"
fi

log "Cloning PostHog repo (background)..."
clone_repo() {
    if [ "$USE_NVME" = true ]; then
        sudo -u ubuntu git clone https://github.com/PostHog/posthog.git /mnt/nvme/posthog
        ln -s /mnt/nvme/posthog "$REPO_DIR"
    else
        sudo -u ubuntu git clone https://github.com/PostHog/posthog.git "$REPO_DIR"
    fi
}
clone_repo &
CLONE_PID=$!

# Install Docker in parallel with the streaming pipelines. policy-rc.d
# blocks the package postinst from auto-starting dockerd, which would
# otherwise race with our in-flight tar extracts writing into
# /var/lib/docker.
log "Installing Docker (in parallel with chunk extract)..."
cat > /usr/sbin/policy-rc.d <<'POLICY'
#!/bin/sh
exit 101
POLICY
chmod +x /usr/sbin/policy-rc.d
install_docker_overlay2
rm -f /usr/sbin/policy-rc.d
log "Docker installed"

# Now wait for any remaining streaming pipelines.
for pid in "${CHUNK_PIDS[@]}"; do
    wait "$pid" || { log "ERROR: streaming pipeline failed"; exit 1; }
done
if [ "${#CHUNK_PIDS[@]}" -gt 0 ]; then
    log "All ${#CHUNK_PIDS[@]} streaming pipelines done in $((SECONDS - stream_start))s"
fi

systemctl start docker
log "Docker started"
log "Docker info: $(docker info --format '{{.DockerRootDir}}, Images: {{.Images}}, Driver: {{.Driver}}')"

log "Waiting for repo clone..."
wait $CLONE_PID || { log "ERROR: git clone failed"; exit 1; }
log "Repo cloned"

log "Pre-populating sandbox config (jetbrains=${SANDBOX_JETBRAINS:-none})..."
SANDBOX_CONFIG_DIR="/home/ubuntu/.posthog-sandboxes"
mkdir -p "$SANDBOX_CONFIG_DIR"
if [ -n "$SANDBOX_JETBRAINS" ]; then
    # Skip the interactive prompt in _resolve_jetbrains_preference. The actual
    # IDE download happens in the background task after the sandbox is live
    # (see "Download JetBrains IDE" block below).
    printf '{"jetbrains": "%s"}\n' "$SANDBOX_JETBRAINS" > "$SANDBOX_CONFIG_DIR/config.json"
else
    echo '{"jetbrains": null}' > "$SANDBOX_CONFIG_DIR/config.json"
fi
chown -R ubuntu:ubuntu "$SANDBOX_CONFIG_DIR"

log "Fetching branch $SANDBOX_BRANCH..."
cd "$REPO_DIR"
sudo -u ubuntu HOME=/home/ubuntu git fetch origin --quiet
if sudo -u ubuntu HOME=/home/ubuntu git fetch origin "$SANDBOX_BRANCH" --quiet 2>/dev/null; then
    log "Checking out existing branch $SANDBOX_BRANCH..."
    sudo -u ubuntu HOME=/home/ubuntu git checkout "$SANDBOX_BRANCH"
else
    log "Branch $SANDBOX_BRANCH not found on remote, creating from origin/master..."
    sudo -u ubuntu HOME=/home/ubuntu git checkout -b "$SANDBOX_BRANCH" origin/master
fi

# Wait for the background Tailscale HTTPS cert task (kicked off right after
# `tailscale up`). By now it's almost certainly done — docker install, archive
# extract, and git clone have been running in parallel for 60+s. If it isn't,
# we block here for the remainder.
#
# We need SANDBOX_JS_URL *before* `bin/sandbox create` because it's baked into
# the JS bundle and used as Django's SITE_URL. Whatever value we pick here is
# what the browser must hit for cookies + asset paths to line up, so it has
# to match the tailscale serve listener below exactly.
#
# HTTPS path gives HTTP/2 multiplexing (~2000 Vite asset requests over one
# connection instead of the HTTP/1.1 6-per-origin cap on a ~70ms tailnet RTT).
# HTTP path is the fallback when the tailnet has no HTTPS cert issuance
# enabled — still same-origin, just slower.
HTTPS_OK=false
if [ -n "$CERT_PID" ]; then
    log "Waiting for Tailscale HTTPS cert..."
    wait "$CERT_PID" || true
    if [ "$(cat "$CERT_STATUS_FILE" 2>/dev/null)" = "ok" ]; then
        HTTPS_OK=true
        log "Cert ready."
    else
        log "tailscale cert failed. Enable HTTPS in https://login.tailscale.com/admin/dns to get HTTP/2. Falling back to HTTP."
        cat "$CERT_LOG" 2>/dev/null || true
    fi
fi

if [ "$HTTPS_OK" = true ]; then
    SANDBOX_JS_URL="https://$FQDN"
else
    # No port: tailscale serve --http=80 listens on 80, which is implicit in
    # the browser URL. If we kept the :48001 here, assets would load from a
    # different origin than the page and we'd lose the @vite same-origin
    # routing that's the whole point of this branch.
    SANDBOX_JS_URL="http://$SANDBOX_HOSTNAME"
fi
USER_URL="$SANDBOX_JS_URL"

# Prepare the JetBrains bind mount directory. The IDE is downloaded here
# *after* the sandbox is live (see background task below), keeping it out of
# the S3 cache archive and off the critical boot path.
JETBRAINS_HOST_DIR="/opt/jetbrains/idea"
mkdir -p "$JETBRAINS_HOST_DIR"
chown ubuntu:ubuntu "$JETBRAINS_HOST_DIR"
export SANDBOX_JETBRAINS_MOUNT="$JETBRAINS_HOST_DIR"

log "Creating sandbox via bin/sandbox create..."
export SANDBOX_HOSTNAME SANDBOX_JS_URL
sudo -u ubuntu HOME=/home/ubuntu sg docker -c "SANDBOX_HOSTNAME='$SANDBOX_HOSTNAME' SANDBOX_JS_URL='$SANDBOX_JS_URL' SANDBOX_JETBRAINS_MOUNT='$SANDBOX_JETBRAINS_MOUNT' python3 bin/sandbox create '$SANDBOX_BRANCH' --no-attach"

# Now expose the running sandbox via Tailscale Serve. A failure here means
# the sandbox is unreachable — let set -e propagate so BOOT_STATUS=failed.
if [ "$HTTPS_OK" = true ]; then
    log "Enabling HTTPS + HTTP/2 via tailscale serve (port 443)..."
    tailscale serve --bg --https=443 http://localhost:48001
else
    log "Exposing sandbox on port 80 via Tailscale Serve..."
    tailscale serve --bg --http=80 http://localhost:48001
fi

# Container is running, tmux + Claude are live, tailscale serve is up.
# Emit the ready marker so the CLI can attach immediately — the app is
# still booting (migrations, deps) but the user can start working in
# Claude while that happens, exactly like the local flow.
log "Cloud sandbox ready — attach now, app still booting"
log "PostHog will be available at $USER_URL once healthy"

# Download JetBrains IDE into the bind-mounted host directory, then trigger
# in-container setup (backend registration, plugins, SDK config). Runs in the
# background so the user can start working immediately.
if [ -n "$SANDBOX_JETBRAINS" ]; then
    (
        # Map preference to JetBrains product code
        case "$SANDBOX_JETBRAINS" in
            intellij) JB_CODE="IIU" ;;
            pycharm)  JB_CODE="PCP" ;;
            *)        log "Unknown JetBrains preference: $SANDBOX_JETBRAINS"; exit 1 ;;
        esac

        JB_API="https://data.services.jetbrains.com/products/releases?code=${JB_CODE}&latest=true&type=release"
        JB_URL=$(curl -sfL "$JB_API" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data['${JB_CODE}'][0]['downloads']['linux']['link'])")

        log "Downloading JetBrains $SANDBOX_JETBRAINS to $JETBRAINS_HOST_DIR (background)..."
        curl -fSL "$JB_URL" | tar -xzf - -C "$JETBRAINS_HOST_DIR" --strip-components=1
        log "JetBrains $SANDBOX_JETBRAINS downloaded"

        # Derive container name: sandbox-{slugified_branch}-app-1
        SLUG=$(echo "$SANDBOX_BRANCH" | tr '/' '-' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g')
        CONTAINER="sandbox-${SLUG}-app-1"

        if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
            log "Triggering JetBrains setup inside $CONTAINER..."
            docker exec -e SANDBOX_MODE=setup-jetbrains "$CONTAINER" python3 bin/sandbox-entrypoint.py || \
                log "WARNING: JetBrains in-container setup failed (will retry on next container start)"
        else
            log "Container $CONTAINER not running — JetBrains setup will run on next start"
        fi
    ) >> /var/log/sandbox-boot.log 2>&1 &
fi

# Health poll runs in the background so it doesn't block the CLI attach.
(
    HEALTH_DEADLINE=$((SECONDS + 600))
    while [ "$SECONDS" -lt "$HEALTH_DEADLINE" ]; do
        if curl -sf "http://localhost:48001/_health" > /dev/null 2>&1; then
            log "App is healthy (total boot time: ${SECONDS}s)"
            BOOT_STATUS="complete"
            echo "$BOOT_STATUS" > /var/log/sandbox-boot-status
            exit 0
        fi
        sleep 5
    done
    log "ERROR: App did not become healthy within 600s"
    BOOT_STATUS="failed"
    echo "$BOOT_STATUS" > /var/log/sandbox-boot-status
) &

BOOT_STATUS="complete"
