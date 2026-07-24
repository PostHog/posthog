#!/bin/bash
# Patches the Electron binary's Info.plist to show "PostHog (Development)" in the macOS menu bar

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
PLIST_FILE="$REPO_ROOT/node_modules/electron/dist/Electron.app/Contents/Info.plist"

if [ ! -f "$PLIST_FILE" ]; then
  exit 0
fi

if /usr/libexec/PlistBuddy -c "Print :CFBundleName" "$PLIST_FILE" | grep -q "PostHog (Development)"; then
  exit 0
fi

/usr/libexec/PlistBuddy -c "Set :CFBundleName 'PostHog (Development)'" "$PLIST_FILE"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName 'PostHog (Development)'" "$PLIST_FILE"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier 'com.posthog.array.dev'" "$PLIST_FILE"
