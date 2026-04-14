#!/usr/bin/env bash
#
# User data script for the cloud cache builder instance.
#
# Runs on a stock Ubuntu 24.04 EC2 instance. Installs Docker, builds the
# sandbox database cache, archives /var/lib/docker, and uploads to S3.
# The instance shuts itself down when done (or on error).
#
# Placeholders replaced by bin/sandbox at launch time:
#   __AWS_CREDENTIALS_B64__  — base64-encoded AWS credentials (env vars)
#   __S3_BUCKET__            — target S3 bucket
#   __S3_KEY__               — target S3 object key
#   __AWS_REGION__           — AWS region for S3 upload
#
set -euo pipefail
exec > /var/log/sandbox-build-cache.log 2>&1

SECONDS=0
log() { echo "==> [${SECONDS}s] $*"; }

# Shut down on exit (success or failure) to avoid burning EC2 costs.
BUILD_STATUS="failed"
cleanup() {
    log "Build status: $BUILD_STATUS"
    echo "$BUILD_STATUS" > /var/log/sandbox-build-status
    shutdown -h now
}
trap cleanup EXIT

# Shared host provisioning helpers (setup_nvme, install_docker_overlay2).
# Inlined at render time by bin/sandbox_cloud.py::_render_template.
__PROVISION_HOST__

log "Cache build starting at $(date)"

AWS_CREDENTIALS_B64="__AWS_CREDENTIALS_B64__"
S3_BUCKET="__S3_BUCKET__"
S3_KEY="__S3_KEY__"
AWS_REGION="__AWS_REGION__"

if [ -n "$AWS_CREDENTIALS_B64" ]; then
    eval "$(echo "$AWS_CREDENTIALS_B64" | base64 -d)"
fi

log "Setting up NVMe instance store..."
setup_nvme
if [ "$USE_NVME" = true ]; then
    # Let bursty writes (tar pack, cargo compile output) buffer longer in
    # RAM before hitting the device, and keep the dentry/inode cache around
    # so cargo's per-file metadata lookups stay warm.
    sysctl -w vm.dirty_ratio=40 vm.vfs_cache_pressure=50 >/dev/null
fi

log "Installing base tools + Docker..."
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg zstd git python3-yaml unzip
install_docker_overlay2
log "Docker installed"

if [ "$USE_NVME" = true ]; then
    systemctl stop docker.socket docker
    mkdir -p /mnt/nvme/docker
    rm -rf /var/lib/docker
    ln -s /mnt/nvme/docker /var/lib/docker
    systemctl start docker
    log "Docker redirected to NVMe"
fi

log "Installing AWS CLI..."
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install
rm -rf /tmp/awscliv2.zip /tmp/aws
log "AWS CLI installed: $(aws --version)"

BUILD_BRANCH="__BUILD_BRANCH__"
log "Cloning PostHog repo..."
cd /home/ubuntu
if [ "$USE_NVME" = true ]; then
    sudo -u ubuntu git clone https://github.com/PostHog/posthog.git /mnt/nvme/posthog
    ln -s /mnt/nvme/posthog /home/ubuntu/posthog
else
    sudo -u ubuntu git clone https://github.com/PostHog/posthog.git
fi
cd posthog
if [ -n "$BUILD_BRANCH" ]; then
    log "Checking out branch: $BUILD_BRANCH"
    sudo -u ubuntu git fetch origin "$BUILD_BRANCH"
    sudo -u ubuntu git checkout "$BUILD_BRANCH"
fi
log "Repo at $(sudo -u ubuntu git rev-parse --short HEAD) ($(sudo -u ubuntu git rev-parse --abbrev-ref HEAD))"

log "Building database cache (this takes ~10-15 min)..."
sudo -u ubuntu sg docker -c "python3 bin/sandbox rebuild-cache"
log "Database cache built"

# JetBrains IDEs are no longer pre-installed into the cache archive.
# cloud-init.sh downloads the chosen IDE into a bind-mounted host directory
# (/opt/jetbrains/idea) after the sandbox is live, keeping ~1.5 GB out of the
# S3 archive and off the critical boot path.

log "Creating split archive of Docker data..."
log "Docker data size: $(du -sh /var/lib/docker | cut -f1)"
log "Volume breakdown:"
du -sh /var/lib/docker/volumes/*/ 2>/dev/null | while read -r line; do log "  $line"; done
log "Top-level breakdown:"
du -sh /var/lib/docker/*/ 2>/dev/null | while read -r line; do log "  $line"; done
systemctl stop docker.socket docker

NUM_CACHE_CHUNKS=4

if [ "$USE_NVME" = true ]; then
    ARCHIVE_DIR="/mnt/nvme/docker-cache"
else
    ARCHIVE_DIR="/tmp/docker-cache"
fi
mkdir -p "$ARCHIVE_DIR"

# Base archive: everything except top-level overlay2 AND except the
# sandbox-cargo-target volume. cargo-target (rust build cache) ships as a
# separate chunk so cloud-init can extract it AFTER the sandbox container
# starts — rust services only build on first invocation (well after
# posthog main is up), so pulling cargo-target off the critical boot
# path saves its extract time wholesale.
# Can't use --exclude=overlay2 because it also strips image/overlay2/.
(cd /var/lib/docker && ls -1 | grep -v '^overlay2$' | tar cf - \
    --exclude='volumes/sandbox-cargo-target' -T -) \
    | zstd -T0 -3 > "$ARCHIVE_DIR/base.tar.zst" &
BASE_PID=$!

# Cargo-target contents as its own archive. Archived relative to _data/
# so the consumer can extract straight into
# /var/lib/docker/volumes/sandbox-cargo-target/_data/ without path
# wrappers.
CARGO_TARGET_DATA=/var/lib/docker/volumes/sandbox-cargo-target/_data
if [ -d "$CARGO_TARGET_DATA" ] && [ -n "$(ls -A "$CARGO_TARGET_DATA" 2>/dev/null)" ]; then
    log "Packaging cargo-target ($(du -sh "$CARGO_TARGET_DATA" | cut -f1))..."
    (cd "$CARGO_TARGET_DATA" && tar cf - .) \
        | zstd -T0 -3 > "$ARCHIVE_DIR/cargo-target.tar.zst" &
fi

# Split overlay2 into chunks for parallel extraction on the consumer side.
# Round-robin assignment by sorted entry name distributes layers roughly evenly.
if [ -d "/var/lib/docker/overlay2" ]; then
    ls -1 /var/lib/docker/overlay2 > /tmp/overlay2-entries.txt
    TOTAL_ENTRIES=$(wc -l < /tmp/overlay2-entries.txt)
    log "Splitting $TOTAL_ENTRIES overlay2 entries across $NUM_CACHE_CHUNKS chunks..."

    for i in $(seq 0 $((NUM_CACHE_CHUNKS - 1))); do
        awk -v c="$i" -v n="$NUM_CACHE_CHUNKS" \
            '(NR-1) % n == c {print "overlay2/" $0}' \
            /tmp/overlay2-entries.txt > "/tmp/overlay2-chunk-${i}.txt"
        tar cf - -C /var/lib/docker -T "/tmp/overlay2-chunk-${i}.txt" \
            | zstd -T0 -3 > "$ARCHIVE_DIR/overlay2-${i}.tar.zst" &
    done
fi

wait "$BASE_PID"
wait
log "All archive chunks created"

# Build manifest listing the chunks
S3_PREFIX="${S3_KEY%.tar.zst}"
python3 -c "
import json, os
archive_dir = '$ARCHIVE_DIR'
chunks = sorted(f for f in os.listdir(archive_dir) if f.endswith('.tar.zst'))
with open(os.path.join(archive_dir, 'manifest.json'), 'w') as fh:
    json.dump({'version': 2, 'chunks': chunks}, fh)
for c in chunks:
    size = os.path.getsize(os.path.join(archive_dir, c)) / (1024*1024)
    print(f'  {c}: {size:.0f} MB')
"

log "Uploading to s3://$S3_BUCKET/$S3_PREFIX/..."
aws s3 cp "$ARCHIVE_DIR/" "s3://$S3_BUCKET/$S3_PREFIX/" --recursive --region "$AWS_REGION"
log "Upload complete"

BUILD_STATUS="complete"
log "Cache build complete! Total time: ${SECONDS}s"
