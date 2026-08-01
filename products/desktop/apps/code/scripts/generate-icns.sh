#!/bin/bash

# Generate ICNS file from a source PNG
# Usage: bash scripts/generate-icns.sh [source.png] [output.icns]
# Defaults: source=build/icon@3x.png, output=build/app-icon.icns

set -e

SOURCE_PNG="${1:-build/app-icon.png}"
OUTPUT_ICNS="${2:-build/app-icon.icns}"
ICONSET_DIR=$(mktemp -d)/icon.iconset

if [ ! -f "$SOURCE_PNG" ]; then
  echo "Error: Source PNG not found: $SOURCE_PNG"
  exit 1
fi

mkdir -p "$ICONSET_DIR"

if ! command -v sips &> /dev/null; then
  echo "Warning: sips not found. Skipping ICNS generation (only supported on macOS)."
  exit 0
fi

sips -z 16 16     "$SOURCE_PNG" --out "$ICONSET_DIR/icon_16x16.png" > /dev/null
sips -z 32 32     "$SOURCE_PNG" --out "$ICONSET_DIR/icon_16x16@2x.png" > /dev/null
sips -z 32 32     "$SOURCE_PNG" --out "$ICONSET_DIR/icon_32x32.png" > /dev/null
sips -z 64 64     "$SOURCE_PNG" --out "$ICONSET_DIR/icon_32x32@2x.png" > /dev/null
sips -z 128 128   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_128x128.png" > /dev/null
sips -z 256 256   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_128x128@2x.png" > /dev/null
sips -z 256 256   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_256x256.png" > /dev/null
sips -z 512 512   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_256x256@2x.png" > /dev/null
sips -z 512 512   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_512x512.png" > /dev/null
sips -z 1024 1024 "$SOURCE_PNG" --out "$ICONSET_DIR/icon_512x512@2x.png" > /dev/null

echo "Converting iconset to ICNS..."

# Convert iconset to icns
iconutil -c icns "$ICONSET_DIR" -o "$OUTPUT_ICNS"

# Clean up
rm -rf "$(dirname "$ICONSET_DIR")"

echo "✓ Created $OUTPUT_ICNS"
