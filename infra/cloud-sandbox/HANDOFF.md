# Cloud Sandboxes

## How it works

Cloud sandboxes run on EC2 instances with the same Docker Compose stack as local sandboxes.
No custom AMI is needed — instances boot from a stock Ubuntu 24.04 AMI and download
pre-built Docker data from S3.

**Boot flow** (stock Ubuntu, ~3-5 min total):

1. Install Tailscale, join network (enables SSH for debugging)
2. Write SSH keys + Claude Code auth
3. Install Docker, zstd, git, python3-yaml
4. Detect + format + mount NVMe instance store (m6id has a fast local SSD)
5. Download `docker-data.tar.zst` from S3 via pre-signed URL (~2-5s for ~2GB)
6. Extract to NVMe, symlink `/var/lib/docker`
7. Start Docker (all images + volumes already loaded)
8. Clone PostHog repo (to NVMe if available), checkout branch
9. `bin/sandbox create <branch> --no-attach` (same code path as local — clones into Docker volume)

**Key files:**

- `bin/sandbox` — CLI with `cloud` subcommands (create, destroy, list, shell, logs, etc.)
- `infra/cloud-sandbox/cloud-init.sh` — user data template, does all setup on stock Ubuntu
- `~/.posthog-sandboxes/cloud-config.json` — local config (S3 bucket, AWS settings, Tailscale key)

## Prerequisites

- AWS CLI configured with a profile that has EC2 + S3 access in the target account
- A Tailscale account with a reusable auth key
  (generate at https://login.tailscale.com/admin/settings/keys — enable "Reusable")
- SSH keys in `~/.ssh/*.pub`
- An S3 bucket for the Docker cache archive
- A security group with outbound internet access
- A subnet with internet access (for package installs and S3 download)

## One-time setup

### 1. Create the S3 bucket

```bash
aws s3 mb s3://posthog-sandbox-cache --region us-east-1 --profile remote-dev
```

### 2. Build and upload the Docker cache

This must be done on a **Linux machine** (not macOS) because it archives
`/var/lib/docker` directly. Use an existing cloud sandbox or a fresh EC2 instance.

**Option A: From an existing sandbox or Linux dev machine:**

```bash
# Build the database cache (Postgres + ClickHouse migrations, Docker images)
bin/sandbox rebuild-cache

# Archive Docker data and upload to S3
bin/sandbox cloud upload-cache
```

On first run, `upload-cache` prompts for S3 bucket name and key.
These are saved to `~/.posthog-sandboxes/cloud-config.json`.

**Option B: From a fresh EC2 instance (bootstrapping):**

```bash
# Launch a temporary m6id.2xlarge, SSH in, then:
sudo apt-get update && sudo apt-get install -y docker.io python3-yaml git zstd
sudo usermod -aG docker ubuntu
# Log out and back in for group change
git clone https://github.com/PostHog/posthog.git && cd posthog
python3 bin/sandbox rebuild-cache
python3 bin/sandbox cloud upload-cache
# Then terminate the instance
```

### 3. First cloud sandbox

```bash
bin/sandbox cloud create my-feature-branch
```

On first run, the CLI prompts for:

- **S3 bucket** — where the Docker cache archive lives (default: `posthog-sandbox-cache`)
- **S3 key** — archive filename (default: `docker-data.tar.zst`)
- **Security group ID** — must allow outbound internet
- **Subnet ID** — must have internet access (public or NAT)
- **AWS region** — default: `us-east-1`
- **AWS CLI profile** — default: `default`
- **Tailscale auth key** — reusable key from the Tailscale admin console

These are saved to `~/.posthog-sandboxes/cloud-config.json`. Example:

```json
{
  "s3_bucket": "posthog-sandbox-cache",
  "s3_key": "docker-data.tar.zst",
  "security_group_id": "sg-0bc3b0b24358a9011",
  "subnet_id": "subnet-0c1d4a3f75f7734d8",
  "region": "us-east-1",
  "aws_profile": "remote-dev",
  "tailscale_auth_key": "tskey-auth-..."
}
```

## Daily usage

```bash
# Create a cloud sandbox for a branch
bin/sandbox cloud create my-branch

# List your cloud sandboxes
bin/sandbox cloud list

# SSH into the sandbox (attaches to mprocs tmux session)
bin/sandbox cloud shell my-branch

# Open PostHog web UI in browser
bin/sandbox cloud open my-branch

# Tail boot + app logs
bin/sandbox cloud logs my-branch

# Open VSCode Remote-SSH to the sandbox
bin/sandbox cloud code my-branch

# Open JetBrains Gateway
bin/sandbox cloud idea my-branch

# Terminate the instance
bin/sandbox cloud destroy my-branch
```

## Updating the Docker cache

When the sandbox Docker image changes significantly (new dependencies, schema changes),
rebuild and re-upload the cache:

```bash
# On a Linux machine:
bin/sandbox rebuild-cache
bin/sandbox cloud upload-cache
```

New cloud sandboxes will automatically use the updated cache.
There is no AMI to rebuild — just upload and go.

## Debugging

**Check boot progress** while waiting for Tailscale:

```bash
aws ec2-instance-connect ssh \
    --instance-id <instance-id> \
    --connection-type eice \
    --os-user ubuntu \
    --profile remote-dev
# Then:
sudo cat /var/log/sandbox-boot.log
```

**Once Tailscale is up** (SSH poll succeeds), the CLI automatically tails the boot log.

**Common issues:**

- **SSH poll times out (3 min)**: Cloud-init may have failed before Tailscale joined.
  Use EC2 Instance Connect (above) to check the boot log.
- **S3 download fails**: Pre-signed URL expires after 1 hour.
  If boot takes longer than expected, the download will fail.
  Destroy and recreate.
- **"No Docker cache archive found"**: Run `bin/sandbox cloud upload-cache` first.

## Architecture decisions

- **Stock Ubuntu AMI** — auto-discovered via `aws ec2 describe-images`. No custom AMI
  to build or maintain. Canonical publishes new AMIs regularly; we always get the latest.
- **S3 pre-signed URLs** — instances need no IAM instance profile. The CLI generates
  a 1-hour pre-signed URL at launch time and embeds it in user data.
- **NVMe instance store** — m6id instances have a fast local NVMe SSD (~400GB).
  Docker data and the git repo are placed on NVMe for fast I/O. Falls back to EBS
  gracefully if no NVMe is available.
- **Same code path as local** — `bin/sandbox create` runs identically on cloud and local.
  Cloud-init just sets up the environment (Docker, git clone) before calling it.
