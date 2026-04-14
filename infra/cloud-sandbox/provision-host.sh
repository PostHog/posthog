# Shared EC2 host provisioning helpers — inlined into cloud-init.sh and
# build-cache.sh at render time by bin/sandbox_cloud.py::_render_template.
#
# Defines: USE_NVME (global), setup_nvme, install_docker_overlay2.
# Requires: log() already defined by the caller.

USE_NVME=false

# Detect the first non-root NVMe instance store, format it with tunings
# appropriate for an ephemeral store (no journal, no atime, no reserved root
# space), and mount at /mnt/nvme. Sets USE_NVME=true on success.
setup_nvme() {
    local root_dev dev name nvme_dev=""
    root_dev=$(lsblk -no PKNAME "$(findmnt -n -o SOURCE /)" | head -1)
    for dev in /dev/nvme*n1; do
        name=$(basename "$dev")
        if [ "$name" != "$root_dev" ] && [ -b "$dev" ]; then
            nvme_dev="$dev"
            break
        fi
    done
    if [ -z "$nvme_dev" ]; then
        log "No NVMe instance store found, staying on EBS"
        return
    fi

    log "Found NVMe instance store: $nvme_dev ($(lsblk -no SIZE "$nvme_dev"))"
    mkfs.ext4 -F -m 0 -E lazy_itable_init=1,lazy_journal_init=1 -O ^has_journal -L nvme-docker "$nvme_dev"
    mkdir -p /mnt/nvme
    mount -o noatime,nodiratime,lazytime "$nvme_dev" /mnt/nvme
    chown ubuntu:ubuntu /mnt/nvme
    USE_NVME=true
    log "NVMe mounted at /mnt/nvme ($(df -h /mnt/nvme | tail -1 | awk '{print $2}') total)"
}

# Install Docker CE with the overlay2 storage driver pinned. overlay2 (vs
# containerd-snapshotter) keeps all image layers inside /var/lib/docker, which
# is what the sandbox cache archive ships.
install_docker_overlay2() {
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<'DAEMONJSON'
{
  "features": {"containerd-snapshotter": false},
  "storage-driver": "overlay2"
}
DAEMONJSON
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    usermod -aG docker ubuntu
}
