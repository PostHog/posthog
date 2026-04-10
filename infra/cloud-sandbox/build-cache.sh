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

log "Cache build starting at $(date)"

AWS_CREDENTIALS_B64="__AWS_CREDENTIALS_B64__"
S3_BUCKET="__S3_BUCKET__"
S3_KEY="__S3_KEY__"
AWS_REGION="__AWS_REGION__"

if [ -n "$AWS_CREDENTIALS_B64" ]; then
    eval "$(echo "$AWS_CREDENTIALS_B64" | base64 -d)"
fi

log "Setting up NVMe instance store..."

ROOT_DEV=$(lsblk -no PKNAME "$(findmnt -n -o SOURCE /)" | head -1)
NVME_DEV=""
for dev in /dev/nvme*n1; do
    name=$(basename "$dev")
    if [ "$name" != "$ROOT_DEV" ] && [ -b "$dev" ]; then
        NVME_DEV="$dev"
        break
    fi
done

USE_NVME=false
if [ -n "$NVME_DEV" ]; then
    log "Found NVMe instance store: $NVME_DEV ($(lsblk -no SIZE "$NVME_DEV"))"
    mkfs.ext4 -F -L nvme-docker "$NVME_DEV"
    mkdir -p /mnt/nvme
    mount "$NVME_DEV" /mnt/nvme
    chown ubuntu:ubuntu /mnt/nvme
    USE_NVME=true
else
    log "No NVMe instance store found, building on EBS"
fi

log "Installing Docker..."
# Pin overlay2 storage driver. Docker CE 29+ defaults to containerd snapshotters
# ("overlayfs"), which stores image layers outside /var/lib/docker/. We archive
# /var/lib/docker/ for the sandbox cache, so we need overlay2 to keep everything there.
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
apt-get install -y -qq ca-certificates curl gnupg zstd git python3-yaml unzip
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker ubuntu
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

log "Archiving Docker data..."
log "Docker data size: $(du -sh /var/lib/docker | cut -f1)"
systemctl stop docker.socket docker

# Write archive to NVMe if available (EBS root is only 40GB)
if [ "$USE_NVME" = true ]; then
    ARCHIVE_PATH="/mnt/nvme/docker-data.tar.zst"
else
    ARCHIVE_PATH="/tmp/docker-data.tar.zst"
fi
tar cf - -C /var/lib/docker . | zstd -T0 -3 > "$ARCHIVE_PATH"
log "Archive created: $(du -h "$ARCHIVE_PATH" | cut -f1)"

log "Uploading to s3://$S3_BUCKET/$S3_KEY..."
aws s3 cp "$ARCHIVE_PATH" "s3://$S3_BUCKET/$S3_KEY" --region "$AWS_REGION"
log "Upload complete"

BUILD_STATUS="complete"
log "Cache build complete! Total time: ${SECONDS}s"
