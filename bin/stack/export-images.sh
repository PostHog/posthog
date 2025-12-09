#!/usr/bin/env bash
set -euo pipefail

# Export all Docker images needed for PostHog minimal stack

echo "PostHog Stack Image Export"
echo "============================"
echo ""

# Array of all images from docker-compose.dev-minimal.yml + PostHog web image
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

echo "Images to export:"
printf '%s\n' "${images[@]}"
echo ""

# Pull all images first (skip locally-built images)
echo "Pulling images..."
for image in "${images[@]}"; do
  if [[ "$image" == "posthog/posthog:stack-1.0.0" ]]; then
    echo "  Skipping $image (locally built)"
    continue
  fi
  echo "  Pulling $image..."
  docker pull "$image"
done
echo ""

# Save all images to tarball
output_file="stack-images.tar.gz"
echo "Saving images to $output_file..."
docker save "${images[@]}" | gzip > "$output_file"

# Show file size
size=$(ls -lh "$output_file" | awk '{print $5}')
echo ""
echo "✓ Export complete!"
echo "  File: $output_file"
echo "  Size: $size"
echo ""
echo "To load these images on another machine:"
echo "  gunzip -c $output_file | docker load"
