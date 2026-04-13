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
