#!/usr/bin/env bash
set -euo pipefail

# Test loading images from tarball

tarball="stack-images.tar.gz"

if [ ! -f "$tarball" ]; then
  echo "Error: $tarball not found"
  echo "Run ./export-images.sh first"
  exit 1
fi

echo "PostHog Stack Image Load Test"
echo "=============================="
echo ""

# Images to verify
images=(
  "caddy"
  "clickhouse/clickhouse-server:25.8.12.129"
  "docker.redpanda.com/redpandadata/redpanda:v25.1.9"
  "ghcr.io/posthog/posthog/capture:master"
  "ghcr.io/posthog/posthog/feature-flags:master"
  "minio/minio:RELEASE.2025-04-22T22-12-26Z"
  "postgres:15.12-alpine"
  "redis:6.2.7-alpine"
  "redis:7.2-alpine"
  "zookeeper:3.7.0"
  "posthog/posthog:stack-1.0.0"
)

echo "Loading images from $tarball..."
gunzip -c "$tarball" | docker load
echo ""

echo "Verifying images loaded:"
all_present=true
for image in "${images[@]}"; do
  if docker image inspect "$image" &>/dev/null; then
    echo "  ✓ $image"
  else
    echo "  ✗ $image (MISSING)"
    all_present=false
  fi
done
echo ""

if [ "$all_present" = true ]; then
  echo "✓ All images loaded successfully!"
  echo ""
  echo "You can now run:"
  echo "  docker-compose -f docker-compose.dev-minimal.yml up -d"
else
  echo "✗ Some images are missing"
  exit 1
fi
