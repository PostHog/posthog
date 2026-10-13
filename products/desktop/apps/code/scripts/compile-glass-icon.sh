#!/bin/bash

# Compile liquid glass icon to Assets.car
# Based on: https://www.hendrik-erz.de/post/supporting-liquid-glass-icons-in-apps-without-xcode
#
# NOTE: This requires Xcode 26 (Command Line Tools are not sufficient)
# If you don't have Xcode, you can either:
# 1. Install Xcode from the App Store
# 2. Manually compile Assets.car on a machine with Xcode and commit it
# 3. Skip liquid glass icon support (the app will use the regular .icns icon)

set -e

ICON_PATH="build/Icon.icon"
OUTPUT_PATH="build/Assets.car"
TEMP_DIR=$(mktemp -d)

skip_with_icns_fallback() {
  echo "⚠ $1"
  rm -rf "$TEMP_DIR"
  # Drop any stale catalog so packaging falls back to the .icns icon
  rm -f "$OUTPUT_PATH"
  if [ -n "${CI:-}" ] && [ "$(uname -s)" = "Darwin" ]; then
    echo "  macOS CI builds must ship the liquid-glass icon; check the $ICON_PATH sources and that Xcode 26 is the active toolchain"
    exit 1
  fi
  echo "  Skipping compilation (app will use standard .icns icon)"
  exit 0
}

if [ ! -d "$ICON_PATH" ]; then
  skip_with_icns_fallback "$ICON_PATH not found"
fi

# Check if Assets.car exists and is newer than every file in the icon bundle
if [ -f "$OUTPUT_PATH" ] && [ -z "$(find "$ICON_PATH" -type f -newer "$OUTPUT_PATH")" ]; then
  echo "✓ Assets.car is up to date"
  exit 0
fi

echo "Compiling liquid glass icon..."

# Check if actool is available and functional
if ! command -v actool &> /dev/null; then
  skip_with_icns_fallback "actool not found - Xcode is required to compile liquid glass icons"
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
  skip_with_icns_fallback "actool failed - Xcode is required to compile liquid glass icons"
fi

# Move Assets.car to build directory
if [ -f "$TEMP_DIR/Assets.car" ]; then
  mv "$TEMP_DIR/Assets.car" "$OUTPUT_PATH"
  echo "✓ Compiled Assets.car to $OUTPUT_PATH"
else
  skip_with_icns_fallback "Assets.car not generated - actool needs Xcode 26 or newer to compile .icon bundles"
fi

# Clean up
rm -rf "$TEMP_DIR"
