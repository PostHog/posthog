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
apt-get install -y -qq ca-certificates curl gnupg zstd git python3-yaml aria2

# Download with aria2 (8 connections per chunk — single-conn curl is
# bandwidth-throttled by S3 to ~35 MB/s on this instance, vs aria2's
# ~260 MiB/s). Start the extract for each chunk the moment its download
# finishes, in parallel with the remaining downloads, Docker install,
# and git clone below. policy-rc.d prevents dockerd from auto-starting
# during package install so it doesn't race our tar extracts writing
# into /var/lib/docker.
#
# True streaming extract (extract-while-downloading base) would be ideal
# but aria2 writes pieces out-of-order with multi-connection, and
# single-connection streaming with curl is too slow to feed tar.
# The pragmatic win: overlay2-* chunks (total ~1.7 GB) finish downloading
# quickly and their extract overlaps with base's download window. base's
# extract still starts only after its ~30s download, but it runs
# concurrently with docker install rather than serially after it.
if [ "$USE_NVME" = true ]; then
    ARCHIVE_DL_DIR="/mnt/nvme/docker-cache"
else
    ARCHIVE_DL_DIR="/tmp/docker-cache"
fi
mkdir -p /var/lib/docker "$ARCHIVE_DL_DIR"
CHUNK_PIDS=()
CARGO_TARGET_NAME=""
CARGO_TARGET_URL=""
pipeline_start=$SECONDS
if [ -f /tmp/cache-manifest.json ]; then
    log "Starting download+extract pipelines (aria2 multi-conn + per-chunk extract)..."
    while IFS=$'\t' read -r name url; do
        # cargo-target.tar.zst is the rust build cache. Skip it in the
        # critical-path loop — we populate it in background after docker
        # starts, since rust services don't build until well after posthog
        # main is up.
        if [ "$name" = "cargo-target.tar.zst" ]; then
            CARGO_TARGET_NAME="$name"
            CARGO_TARGET_URL="$url"
            continue
        fi
        (
            for attempt in 1 2 3; do
                if aria2c -x 8 -s 8 --max-connection-per-server=8 \
                        --file-allocation=none --auto-file-renaming=false \
                        --console-log-level=error \
                        -d "$ARCHIVE_DL_DIR" -o "$name" "$url"; then
                    echo "==> [${SECONDS}s] Downloaded $name, extracting..."
                    if tar -C /var/lib/docker -I 'unzstd' -xf "$ARCHIVE_DL_DIR/$name"; then
                        rm -f "$ARCHIVE_DL_DIR/$name"
                        echo "==> [${SECONDS}s] Extracted $name"
                        exit 0
                    fi
                fi
                # Drop partial archive so next aria2 attempt starts clean;
                # --auto-file-renaming=false would otherwise refuse the
                # existing destination or resume a broken download.
                rm -f "$ARCHIVE_DL_DIR/$name"
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
    log "Started ${#CHUNK_PIDS[@]} pipelines (+cargo-target deferred)"
else
    log "WARNING: No cache manifest provided, Docker starts with no cached images"
fi

log "Cloning PostHog repo (background, shallow)..."
clone_repo() {
    local target="$REPO_DIR"
    if [ "$USE_NVME" = true ]; then
        target="/mnt/nvme/posthog"
    fi
    # Shallow clone: workspace population only fetches --depth=50 from the
    # host repo via file:// transport. Clone master first, then fetch the
    # sandbox branch with an explicit refspec so the remote tracking ref
    # gets created (plain `git fetch origin <branch>` only writes FETCH_HEAD).
    sudo -u ubuntu git clone --depth=50 --no-tags \
        https://github.com/PostHog/posthog.git "$target"
    # Fetch the sandbox branch if it's not master
    if [ "$SANDBOX_BRANCH" != "master" ]; then
        sudo -u ubuntu git -C "$target" fetch --depth=50 --no-tags \
            origin "+refs/heads/$SANDBOX_BRANCH:refs/remotes/origin/$SANDBOX_BRANCH" \
            2>/dev/null || true
    fi
    if [ "$USE_NVME" = true ]; then
        ln -s "$target" "$REPO_DIR"
    fi
}
clone_repo &
CLONE_PID=$!

# Install Docker in parallel with the chunk pipelines. policy-rc.d blocks
# the package postinst from auto-starting dockerd, which would otherwise
# race with our in-flight tar extracts writing into /var/lib/docker.
log "Installing Docker (in parallel with chunk extract)..."
cat > /usr/sbin/policy-rc.d <<'POLICY'
#!/bin/sh
exit 101
POLICY
chmod +x /usr/sbin/policy-rc.d
install_docker_overlay2
rm -f /usr/sbin/policy-rc.d
# WARNING: do not add any `apt-get install` between this line and
# `systemctl start docker` below — the new package's postinst would
# auto-start dockerd against a /var/lib/docker possibly still being
# written by chunk extracts, racing tar.
log "Docker installed"

# Now wait for any remaining chunk pipelines.
for pid in "${CHUNK_PIDS[@]}"; do
    wait "$pid" || { log "ERROR: chunk pipeline failed"; exit 1; }
done
if [ "${#CHUNK_PIDS[@]}" -gt 0 ]; then
    log "All ${#CHUNK_PIDS[@]} pipelines done in $((SECONDS - pipeline_start))s"
fi

# Start Docker in the background — it takes ~50s to scan all the restored
# overlay2 layers. While it initializes, we can wait for the repo clone and
# check out the branch in parallel.
systemctl start docker &
DOCKER_START_PID=$!
docker_start_ts=$SECONDS

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

log "Checking out branch $SANDBOX_BRANCH..."
cd "$REPO_DIR"
# Branch was already fetched during the shallow clone above.
if sudo -u ubuntu HOME=/home/ubuntu git checkout "$SANDBOX_BRANCH" 2>/dev/null; then
    log "Checked out existing branch $SANDBOX_BRANCH"
elif sudo -u ubuntu HOME=/home/ubuntu git checkout -b "$SANDBOX_BRANCH" "origin/$SANDBOX_BRANCH" 2>/dev/null; then
    log "Checked out remote branch $SANDBOX_BRANCH"
else
    log "Branch $SANDBOX_BRANCH not found on remote, creating from origin/master..."
    sudo -u ubuntu HOME=/home/ubuntu git checkout -b "$SANDBOX_BRANCH" origin/master
fi

# Now wait for Docker to finish starting.
wait $DOCKER_START_PID || { log "ERROR: Docker failed to start"; exit 1; }
log "Docker started in $((SECONDS - docker_start_ts))s"
log "Docker info: $(docker info --format '{{.DockerRootDir}}, Images: {{.Images}}, Driver: {{.Driver}}')"

# Stage the sandbox-cargo-target volume and background-populate it.
# docker-compose.sandbox.yml declares it external, so it must exist before
# `bin/sandbox create` runs compose. We create the (empty) volume now and
# extract the rust cache into its _data/ directory in the background. No
# compose or bind-mount changes needed — the volume is a normal named
# volume on cloud just like on local, it just happens to be populated
# out-of-band.
#
# Timing: rust services only invoke cargo at first request (long after
# posthog main is up), so cloud-init doesn't need to wait for this.
if [ -n "$CARGO_TARGET_URL" ]; then
    docker volume create sandbox-cargo-target >/dev/null
    CARGO_TARGET_DATA=$(docker volume inspect sandbox-cargo-target --format '{{.Mountpoint}}')
    # Pre-chmod the volume's host directory and tell `bin/sandbox create`
    # to skip its own alpine-chmod pass on this volume. Otherwise
    # `_ensure_cache_volumes()` would spin up an alpine container to
    # `chmod 777 /data` on the live volume concurrently with our tar
    # extract writing into it — a real race, since alpine holds the mount
    # for the duration of `docker run --rm`.
    chmod 777 "$CARGO_TARGET_DATA"
    export SANDBOX_SKIP_VOLUME_CHMOD="sandbox-cargo-target"
    log "Background-extracting cargo-target to $CARGO_TARGET_DATA (resolved: $(realpath "$CARGO_TARGET_DATA"))..."
    (
        cargo_start=$SECONDS
        for attempt in 1 2 3; do
            if aria2c -x 8 -s 8 --max-connection-per-server=8 \
                    --file-allocation=none --auto-file-renaming=false \
                    --console-log-level=error \
                    -d "$ARCHIVE_DL_DIR" -o "$CARGO_TARGET_NAME" "$CARGO_TARGET_URL"; then
                if tar -C "$CARGO_TARGET_DATA" -I 'unzstd' -xf "$ARCHIVE_DL_DIR/$CARGO_TARGET_NAME"; then
                    rm -f "$ARCHIVE_DL_DIR/$CARGO_TARGET_NAME"
                    echo "==> [${SECONDS}s] cargo-target extracted in $((SECONDS - cargo_start))s"
                    exit 0
                fi
            fi
            rm -f "$ARCHIVE_DL_DIR/$CARGO_TARGET_NAME"
            [ "$attempt" = 3 ] && {
                # Wipe the volume so cargo rebuilds from a clean slate.
                # A half-populated cargo-target poisons incremental builds:
                # .fingerprint/ mtimes can cause cargo to skip recompiling
                # a crate whose .rmeta never made it to disk, producing
                # confusing "file not found" errors at link time.
                echo "==> [${SECONDS}s] WARNING: cargo-target extract failed; wiping volume so cargo rebuilds clean" >&2
                find "$CARGO_TARGET_DATA" -mindepth 1 -delete 2>/dev/null || true
                exit 1
            }
            sleep 5
        done
    ) &
    # Intentionally don't capture PID — fire-and-forget. Failure is
    # logged; on permanent failure the volume gets wiped so rust services
    # rebuild from scratch on first invocation instead of mis-hitting
    # partial cache.
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
sudo -u ubuntu HOME=/home/ubuntu sg docker -c "SANDBOX_HOSTNAME='$SANDBOX_HOSTNAME' SANDBOX_JS_URL='$SANDBOX_JS_URL' SANDBOX_JETBRAINS_MOUNT='$SANDBOX_JETBRAINS_MOUNT' SANDBOX_SKIP_VOLUME_CHMOD='${SANDBOX_SKIP_VOLUME_CHMOD:-}' python3 bin/sandbox create '$SANDBOX_BRANCH' --no-attach"

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

# Download JetBrains IDE in the background (script lives in the cloned repo).
if [ -n "$SANDBOX_JETBRAINS" ]; then
    bash "$REPO_DIR/infra/cloud-sandbox/install-jetbrains.sh" \
        "$SANDBOX_JETBRAINS" "$JETBRAINS_HOST_DIR" "$SANDBOX_BRANCH" \
        >> /var/log/sandbox-boot.log 2>&1 &
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
