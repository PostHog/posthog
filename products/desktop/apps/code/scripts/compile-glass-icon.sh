#!/bin/bash

# Compile liquid glass icon to Assets.car
# Based on: https://www.hendrik-erz.de/post/supporting-liquid-glass-icons-in-apps-without-xcode
#
# NOTE: This requires Xcode to be installed (Command Line Tools are not sufficient)
# If you don't have Xcode, you can either:
# 1. Install Xcode from the App Store
# 2. Manually compile Assets.car on a machine with Xcode and commit it
# 3. Skip liquid glass icon support (the app will use the regular .icns icon)

set -e

ICON_PATH="build/icon.icon"
OUTPUT_PATH="build/Assets.car"
TEMP_DIR=$(mktemp -d)

if [ ! -d "$ICON_PATH" ]; then
  echo "⚠ $ICON_PATH not found - skipping liquid glass icon compilation"
  exit 0
fi

# Check if Assets.car exists and is newer than source
if [ -f "$OUTPUT_PATH" ] && [ "$OUTPUT_PATH" -nt "$ICON_PATH/icon.json" ]; then
  echo "✓ Assets.car is up to date"
  exit 0
fi

echo "Compiling liquid glass icon..."

# Check if actool is available and functional
if ! command -v actool &> /dev/null; then
  echo "⚠ actool not found - Xcode is required to compile liquid glass icons"
  echo "  Skipping compilation (app will use standard .icns icon)"
  exit 0
fi

# Try to compile with actool
PARTIAL_INFO_PLIST="$TEMP_DIR/partial-info.plist"

if ! actool "$ICON_PATH" \
  --compile "$TEMP_DIR" \
  --output-format human-readable-text \
  --notices --warnings --errors \
  --output-partial-info-plist "$PARTIAL_INFO_PLIST" \
  --app-icon Icon \
  --include-all-app-icons \
  --enable-on-demand-resources NO \
  --development-region en \
  --target-device mac \
  --minimum-deployment-target 26.0 \
  --platform macosx 2>&1; then
  echo "⚠ actool failed - Xcode is required to compile liquid glass icons"
  echo "  Skipping compilation (app will use standard .icns icon)"
  rm -rf "$TEMP_DIR"
  exit 0
fi

# Move Assets.car to build directory
if [ -f "$TEMP_DIR/Assets.car" ]; then
  mv "$TEMP_DIR/Assets.car" "$OUTPUT_PATH"
  echo "✓ Compiled Assets.car to $OUTPUT_PATH"
else
  echo "⚠ Assets.car not generated - skipping"
fi

# Clean up
rm -rf "$TEMP_DIR"
