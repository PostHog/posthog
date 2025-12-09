# PostHog Stack Installer

Self-contained, offline-capable PostHog development environment packaged as a macOS installer.

## Overview

This installer packages all required Docker images and configuration into a single `.pkg` file that can be distributed via DVD, USB drive, or network share. Perfect for demos, workshops, and onboarding new contributors.

## Quick Start (For Users)

### Prerequisites

- macOS (tested on macOS 12+)
- Docker Desktop installed and running

### Installation

1. Double-click `PostHogStack.pkg` or run:

   ```bash
   sudo installer -pkg PostHogStack.pkg -target /
   ```

2. Start PostHog:

   ```bash
   posthog-stack up
   ```

3. Open your browser to [http://localhost:8000](http://localhost:8000)

### CLI Commands

```bash
posthog-stack up          # Start the stack
posthog-stack down        # Stop the stack
posthog-stack logs        # View all logs
posthog-stack logs db     # View specific service logs
posthog-stack status      # Show running services
posthog-stack reset       # Wipe data and start fresh
posthog-stack version     # Show version
```

## Building the Installer (For Maintainers)

### Step 1: Export Docker Images

This creates a compressed tarball (~3-5GB) with all required images:

```bash
cd bin/stack
./export-images.sh
```

This will:

- Pull all images from docker-compose.dev-minimal.yml
- Save them to `stack-images.tar.gz`
- Display the final file size

### Step 2: Test Image Loading (Optional)

Verify the tarball works correctly:

```bash
./test-load-images.sh
```

This will:

- Load images from the tarball
- Verify all images are present
- Confirm they can be used by docker-compose

### Step 3: Build the .pkg Installer

```bash
./build-installer.sh
```

This creates `PostHogStack.pkg` which includes:

- `stack-images.tar.gz` - All Docker images
- `docker-compose.stack.yml` - Service configuration
- `posthog-stack` - CLI wrapper
- Pre/post-install scripts

### Step 4: Test Installation

```bash
sudo installer -pkg PostHogStack.pkg -target /
posthog-stack up
```

Visit [http://localhost:8000](http://localhost:8000) to verify PostHog is running.

### Step 5: Distribute

Copy `PostHogStack.pkg` to DVD, USB, or network share. Users only need:

1. macOS with Docker Desktop
2. The .pkg file
3. No internet connection required (after Docker Desktop is installed)

## What's Included

The minimal stack includes these services:

### Infrastructure

- **Postgres 15.12** - Main database
- **Redis 6.2 + 7.2** - Caching and queues
- **ClickHouse 25.8** - Analytics database
- **Kafka (Redpanda)** - Event streaming
- **Zookeeper 3.7** - Kafka coordination
- **MinIO** - Object storage

### PostHog Services

- **Caddy** - Reverse proxy
- **Capture** - Event ingestion (Rust)
- **Feature Flags** - Flag evaluation (Rust)

### Developer Tools

Run locally via `bin/start`:

- Web server (Django + React)
- Plugin server (Node.js)
- Celery workers
- Property definitions service

## Architecture

```
┌─────────────────────────────────────┐
│  posthog-stack CLI                  │
│  (/usr/local/bin/posthog-stack)     │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  /usr/local/posthog-stack/          │
│  ├── stack-images.tar.gz (4GB)      │
│  └── docker-compose.stack.yml       │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Docker Containers                  │
│  (11 services)                      │
└─────────────────────────────────────┘
```

## Differences from `bin/start`

| Feature | bin/start | posthog-stack |
|---------|-----------|---------------|
| Use case | Active development | Demos, workshops |
| Hot reload | ✓ Yes | ✗ No |
| Source code | Required | Not required |
| Internet | Required | Not required (after install) |
| Setup time | ~5-10 min | ~2-3 min |
| Services | Runs locally + Docker | All in Docker |

## Troubleshooting

### "Docker is not running"

Start Docker Desktop before running `posthog-stack up`.

### "Port 8000 is already in use"

Another service is using port 8000. Stop it or change the port in `docker-compose.stack.yml`.

### "Images failed to load"

The tarball may be corrupted. Re-run `./export-images.sh` to regenerate it.

### Services not starting

Check logs:

```bash
posthog-stack logs
```

### Completely reset everything

```bash
posthog-stack reset
```

## Uninstallation

```bash
# Stop and remove containers
posthog-stack down

# Remove installation (requires sudo)
sudo rm -rf /usr/local/posthog-stack
sudo rm /usr/local/bin/posthog-stack
```

## File Sizes

- Uncompressed images: ~8-10GB
- Compressed tarball: ~3-5GB
- Final .pkg installer: ~3-5GB
- Installed on disk: ~10-12GB (includes volumes)

## Updates

To update to a newer version:

1. Pull latest images: `docker-compose -f docker-compose.dev-minimal.yml pull`
2. Re-run: `./export-images.sh`
3. Re-run: `./build-installer.sh`
4. Distribute new `PostHogStack.pkg`

## Support

- Documentation: <https://posthog.com/docs>
- Issues: <https://github.com/PostHog/posthog/issues>
- Community: <https://posthog.com/questions>
