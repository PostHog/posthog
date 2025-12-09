#!/usr/bin/env bash
set -euo pipefail

# Build PostHog Stack .pkg installer for macOS

echo "PostHog Stack Installer Builder"
echo "================================"
echo ""

# Check prerequisites
if [ ! -f "stack-images.tar.gz" ]; then
  echo "Error: stack-images.tar.gz not found"
  echo "Run ./export-images.sh first"
  exit 1
fi

if [ ! -f "postgres-data.tar.gz" ]; then
  echo "Error: postgres-data.tar.gz not found"
  echo "Export Postgres volume first"
  exit 1
fi

if [ ! -f "clickhouse-data.tar.gz" ]; then
  echo "Error: clickhouse-data.tar.gz not found"
  echo "Export ClickHouse volume first"
  exit 1
fi

if [ ! -f "../../docker-compose.dev-stack.yml" ]; then
  echo "Error: docker-compose.dev-stack.yml not found"
  exit 1
fi

# Clean previous build
rm -rf installer-build
mkdir -p installer-build/payload/{posthog-stack,bin}
mkdir -p installer-build/scripts

echo "Preparing installer files..."

# Merge docker-compose files into self-contained stack file
echo "Merging docker-compose files (including web services)..."
./merge-compose.sh ../../docker-compose.dev-stack.yml > docker-compose.stack.yml

# Copy payload files to correct locations
cp stack-images.tar.gz installer-build/payload/posthog-stack/
cp postgres-data.tar.gz installer-build/payload/posthog-stack/
cp clickhouse-data.tar.gz installer-build/payload/posthog-stack/
cp docker-compose.stack.yml installer-build/payload/posthog-stack/
cp posthog-stack installer-build/payload/bin/

# Create postinstall script
cat > installer-build/scripts/postinstall << 'EOF'
#!/bin/bash

# Files are already installed to /usr/local/posthog-stack by pkgbuild
# Just need to set permissions on the CLI

chmod +x /usr/local/bin/posthog-stack

echo ""
echo "✓ PostHog Stack installed successfully!"
echo ""
echo "Installation directory: /usr/local/posthog-stack"
echo "CLI installed to: /usr/local/bin/posthog-stack"
echo ""
echo "Next steps:"
echo "  1. Ensure Docker Desktop is running"
echo "  2. Run: posthog-stack up"
echo "  3. Open: http://localhost:8000"
echo ""
EOF

chmod +x installer-build/scripts/postinstall

# Create preinstall script
cat > installer-build/scripts/preinstall << 'EOF'
#!/bin/bash

# Check if Docker is installed (warning only, don't fail)
docker_found=false
for docker_path in "/usr/local/bin/docker" "/opt/homebrew/bin/docker" "$(which docker 2>/dev/null)"; do
  if [ -x "$docker_path" ]; then
    docker_found=true
    break
  fi
done

if [ "$docker_found" = false ]; then
  echo ""
  echo "⚠ Warning: Docker not found in common locations"
  echo "You'll need Docker Desktop installed to run PostHog Stack"
  echo "Install from: https://www.docker.com/products/docker-desktop"
  echo ""
  echo "Installation will continue..."
  echo ""
else
  echo "✓ Docker found"
fi

# Always succeed - Docker check happens when user runs posthog-stack up
exit 0
EOF

chmod +x installer-build/scripts/preinstall

# Build the package
echo "Building PostHogStack.pkg..."
pkgbuild \
  --root installer-build/payload \
  --scripts installer-build/scripts \
  --identifier com.posthog.stack \
  --version 1.0.0 \
  --install-location /usr/local \
  PostHogStack.pkg

# Show package info
size=$(ls -lh PostHogStack.pkg | awk '{print $5}')
echo ""
echo "✓ Package built successfully!"
echo "  File: PostHogStack.pkg"
echo "  Size: $size"
echo ""
echo "To test installation:"
echo "  sudo installer -pkg PostHogStack.pkg -target /"
echo ""
echo "To distribute:"
echo "  Copy PostHogStack.pkg to a DVD, USB drive, or network share"
