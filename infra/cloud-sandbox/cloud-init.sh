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
#   4. Install Docker, aria2, zstd, git, python3-yaml (single apt batch)
#   5. Background: S3 download (aria2c, 16 connections) + git clone
#   6. Foreground: Docker repo + install
#   7. Wait for S3 download, extract to NVMe, symlink /var/lib/docker
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

log "Cloud sandbox boot starting at $(date)"

SANDBOX_BRANCH="__SANDBOX_BRANCH__"
SANDBOX_OWNER="__SANDBOX_OWNER__"
SANDBOX_HOSTNAME="__SANDBOX_HOSTNAME__"
CLAUDE_CREDENTIALS_B64="__CLAUDE_CREDENTIALS_B64__"
CLAUDE_SETTINGS_B64="__CLAUDE_SETTINGS_B64__"
CLAUDE_JSON_B64="__CLAUDE_JSON_B64__"
S3_ARCHIVE_URL_B64="__S3_ARCHIVE_URL_B64__"
TAILSCALE_AUTH_KEY_B64="__TAILSCALE_AUTH_KEY_B64__"
SSH_AUTHORIZED_KEYS_B64="__SSH_AUTHORIZED_KEYS_B64__"

S3_ARCHIVE_URL=""
if [ -n "$S3_ARCHIVE_URL_B64" ]; then
    S3_ARCHIVE_URL=$(echo "$S3_ARCHIVE_URL_B64" | base64 -d)
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

ROOT_DEV=$(lsblk -no PKNAME "$(findmnt -n -o SOURCE /)" | head -1)
log "Root device: $ROOT_DEV"
log "Available NVMe devices: $(ls /dev/nvme*n1 2>/dev/null || echo 'none')"

NVME_DEV=""
for dev in /dev/nvme*n1; do
    name=$(basename "$dev")
    if [ "$name" != "$ROOT_DEV" ] && [ -b "$dev" ]; then
        NVME_DEV="$dev"
        break
    fi
done

if [ -z "$NVME_DEV" ]; then
    log "WARNING: No NVMe instance store found, staying on EBS"
else
    log "Found NVMe instance store: $NVME_DEV"
    log "NVMe device size: $(lsblk -no SIZE "$NVME_DEV")"

    # Tunings for an ephemeral store where crash consistency doesn't matter:
    #   -O ^has_journal        skip the journal entirely
    #   -E lazy_*_init=1       don't zero the inode table / journal up front
    #   -m 0                   don't reserve 5% for root (reclaims ~20-30 GB)
    # Mount with noatime,nodiratime,lazytime so atime/mtime/ctime updates
    # stay in RAM instead of causing metadata writes on every file touch
    # (cargo, pnpm, and tar extract all do millions of these).
    mkfs.ext4 -F -m 0 -E lazy_itable_init=1,lazy_journal_init=1 -O ^has_journal -L nvme-docker "$NVME_DEV"
    mkdir -p /mnt/nvme
    mount -o noatime,nodiratime,lazytime "$NVME_DEV" /mnt/nvme
    chown ubuntu:ubuntu /mnt/nvme
    log "NVMe mounted at /mnt/nvme ($(df -h /mnt/nvme | tail -1 | awk '{print $2}') total)"

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
if [ -n "$NVME_DEV" ]; then
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
    log "WARNING: no NVMe device, skipping swap setup"
fi

log "Installing base dependencies..."
# Pin overlay2 storage driver to match the build-cache archive.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'DAEMONJSON'
{
  "features": {
    "containerd-snapshotter": false
  },
  "storage-driver": "overlay2"
}
DAEMONJSON
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg zstd git python3-yaml aria2

# Download to NVMe (or /tmp on EBS) so extraction is NVMe→NVMe.
if [ -n "$NVME_DEV" ]; then
    ARCHIVE_DL_PATH="/mnt/nvme/docker-data.tar.zst"
else
    ARCHIVE_DL_PATH="/tmp/docker-data.tar.zst"
fi

S3_DL_PID=""
if [ -n "$S3_ARCHIVE_URL" ]; then
    log "Starting S3 download (background, 16 parallel connections)..."
    s3_download() {
        local dl_dir dl_name
        dl_dir=$(dirname "$ARCHIVE_DL_PATH")
        dl_name=$(basename "$ARCHIVE_DL_PATH")
        for attempt in 1 2 3; do
            if aria2c -x 16 -s 16 -j 1 --max-connection-per-server=16 \
                    --file-allocation=none --auto-file-renaming=false \
                    --console-log-level=warn --summary-interval=10 \
                    -d "$dl_dir" -o "$dl_name" "$S3_ARCHIVE_URL"; then
                return 0
            fi
            log "S3 download attempt $attempt failed, retrying in 5s..."
            rm -f "$ARCHIVE_DL_PATH"
            sleep 5
        done
        return 1
    }
    s3_download &
    S3_DL_PID=$!
fi

log "Cloning PostHog repo (background)..."
clone_repo() {
    if [ -n "$NVME_DEV" ]; then
        sudo -u ubuntu git clone https://github.com/PostHog/posthog.git /mnt/nvme/posthog
        ln -s /mnt/nvme/posthog "$REPO_DIR"
    else
        sudo -u ubuntu git clone https://github.com/PostHog/posthog.git "$REPO_DIR"
    fi
}
clone_repo &
CLONE_PID=$!

log "Installing Docker..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker ubuntu

# Stop Docker — we need to populate /var/lib/docker from the S3 cache first.
systemctl stop docker.socket docker
log "Docker installed (stopped for cache extraction)"
if [ -n "$S3_DL_PID" ]; then
    log "Waiting for S3 download..."
    wait "$S3_DL_PID" || { log "ERROR: All S3 download attempts failed"; exit 1; }
    log "Downloaded $(du -h "$ARCHIVE_DL_PATH" | cut -f1)"

    log "Extracting Docker cache..."
    mkdir -p /var/lib/docker
    extract_start=$SECONDS
    tar -C /var/lib/docker -I 'zstd -T0' -xf "$ARCHIVE_DL_PATH"
    log "Extracted Docker cache in $((SECONDS - extract_start))s"
    rm -f "$ARCHIVE_DL_PATH"
else
    log "WARNING: No S3 archive URL provided, Docker starts with no cached images"
fi

systemctl start docker
log "Docker started"
log "Docker info: $(docker info --format '{{.DockerRootDir}}, Images: {{.Images}}, Driver: {{.Driver}}')"

log "Waiting for repo clone..."
wait $CLONE_PID || { log "ERROR: git clone failed"; exit 1; }
log "Repo cloned"

log "Pre-populating sandbox config..."
SANDBOX_CONFIG_DIR="/home/ubuntu/.posthog-sandboxes"
mkdir -p "$SANDBOX_CONFIG_DIR"
echo '{"jetbrains": null}' > "$SANDBOX_CONFIG_DIR/config.json"
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
# We need the cert before `bin/sandbox create` so the SANDBOX_JS_URL gets
# baked into JS bundles / HMR client. HTTP/2 requires TLS in browsers, and
# Tailscale's ACME integration gives us a real Let's Encrypt cert for the
# node's .ts.net FQDN — no self-signed cert warnings. The win: the browser
# can multiplex ~2000 Vite asset requests over one connection instead of
# hitting HTTP/1.1's 6-per-origin cap on a ~70ms tailnet RTT (the difference
# between a 40s and a 5s page load).
SANDBOX_JS_URL=""
USER_URL="http://$SANDBOX_HOSTNAME:48001"
if [ -n "$CERT_PID" ]; then
    log "Waiting for Tailscale HTTPS cert..."
    wait "$CERT_PID" || true
    if [ "$(cat "$CERT_STATUS_FILE" 2>/dev/null)" = "ok" ]; then
        SANDBOX_JS_URL="https://$FQDN"
        USER_URL="https://$FQDN"
        log "Cert ready."
    else
        log "WARNING: tailscale cert failed. Enable HTTPS in https://login.tailscale.com/admin/dns to get HTTP/2. Falling back to HTTP."
        cat "$CERT_LOG" 2>/dev/null || true
    fi
fi

log "Creating sandbox via bin/sandbox create..."
export SANDBOX_HOSTNAME SANDBOX_JS_URL
sudo -u ubuntu HOME=/home/ubuntu sg docker -c "SANDBOX_HOSTNAME='$SANDBOX_HOSTNAME' SANDBOX_JS_URL='$SANDBOX_JS_URL' python3 bin/sandbox create '$SANDBOX_BRANCH' --no-attach"

# Now expose the running sandbox via Tailscale Serve. HTTPS path (if the
# cert call above succeeded) gives us HTTP/2 multiplexing; HTTP path is the
# same fallback we had before — slower but functional.
if [ -n "$SANDBOX_JS_URL" ]; then
    log "Enabling HTTPS + HTTP/2 via tailscale serve (port 443)..."
    tailscale serve --bg --https=443 http://localhost:48001 \
        || log "WARNING: tailscale serve --https failed"
else
    log "Exposing sandbox on port 80 via Tailscale Serve..."
    tailscale serve --bg --http=80 http://localhost:48001 \
        || log "WARNING: tailscale serve failed — fall back to http://$SANDBOX_HOSTNAME:48001"
fi

log "Waiting for app to be healthy..."
HEALTH_DEADLINE=$((SECONDS + 600))
while [ "$SECONDS" -lt "$HEALTH_DEADLINE" ]; do
    if curl -sf "http://localhost:48001/_health" > /dev/null 2>&1; then
        log "App is healthy"
        break
    fi
    sleep 5
done

BOOT_STATUS="complete"
log "Cloud sandbox boot complete at $(date)"
log "Total boot time: ${SECONDS}s"
log "Tailscale hostname: $SANDBOX_HOSTNAME"
log "PostHog will be available at $USER_URL once healthy"
