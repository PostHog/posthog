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

# Install JetBrains IDEs into shared Docker volumes so cloud sandboxes skip
# the ~40s download during bin/sandbox create.
install_jetbrains_to_volume() {
    local code="$1" name="$2" volume="$3"
    local check
    check=$(docker run --rm -v "${volume}:/opt/idea" alpine sh -c \
        "test -x /opt/idea/bin/remote-dev-server.sh && echo yes" 2>/dev/null || true)
    if [ "$check" = "yes" ]; then
        log "$name already installed in $volume"
        return
    fi
    local api_url="https://data.services.jetbrains.com/products/releases?code=${code}&latest=true&type=release"
    local download_url
    download_url=$(curl -sfL "$api_url" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data['${code}'][0]['downloads']['linux']['link'])")
    log "Downloading $name..."
    docker run --rm -v "${volume}:/opt/idea" -e "DL_URL=${download_url}" alpine sh -c \
        'apk add --no-cache curl > /dev/null 2>&1 && curl -fSL "$DL_URL" | tar -xzf - -C /opt/idea --strip-components=1'
    log "$name installed into $volume"
}

log "Installing JetBrains IDEs into cache..."
install_jetbrains_to_volume "IIU" "IntelliJ IDEA Ultimate" "sandbox-intellij" &
JB_PID1=$!
install_jetbrains_to_volume "PCP" "PyCharm Professional" "sandbox-pycharm" &
JB_PID2=$!
wait $JB_PID1 || { log "ERROR: IntelliJ install failed"; exit 1; }
wait $JB_PID2 || { log "ERROR: PyCharm install failed"; exit 1; }
log "JetBrains IDEs ready"

log "Creating split archive of Docker data..."
log "Docker data size: $(du -sh /var/lib/docker | cut -f1)"
systemctl stop docker.socket docker

NUM_CACHE_CHUNKS=4

if [ "$USE_NVME" = true ]; then
    ARCHIVE_DIR="/mnt/nvme/docker-cache"
else
    ARCHIVE_DIR="/tmp/docker-cache"
fi
mkdir -p "$ARCHIVE_DIR"

# Base archive: everything except top-level overlay2.
# Can't use --exclude=overlay2 because it also strips image/overlay2/.
(cd /var/lib/docker && ls -1 | grep -v '^overlay2$' | tar cf - -T -) | zstd -T0 -3 > "$ARCHIVE_DIR/base.tar.zst" &
BASE_PID=$!

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
