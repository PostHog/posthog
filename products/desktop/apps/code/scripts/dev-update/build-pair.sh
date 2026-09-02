#!/usr/bin/env bash
# Build a signed OLD (1.0.0) app to run plus a signed NEW (2.0.0) feed for the
# macOS auto-update E2E. Real signing needs CSC_LINK (set in CI); locally it uses
# whatever identity electron-builder finds. Run from apps/code.
#
# Set CHAIN_VERSION (e.g. 3.0.0) to also build a second, newer feed into
# out/dev-update-feed-chain for the chained update E2E (update-chain.spec.ts).
set -euo pipefail

cd "$(dirname "$0")/../.."

OLD_VERSION="${OLD_VERSION:-1.0.0}"
NEW_VERSION="${NEW_VERSION:-2.0.0}"
CHAIN_VERSION="${CHAIN_VERSION:-}"
FEED_DIR="out/dev-update-feed"
CHAIN_FEED_DIR="out/dev-update-feed-chain"

export SKIP_NOTARIZE="${SKIP_NOTARIZE:-1}"

echo "==> electron-vite build"
pnpm exec electron-vite build

if [[ -n "$CHAIN_VERSION" ]]; then
  echo "==> build CHAIN $CHAIN_VERSION (second feed artifacts)"
  pnpm exec electron-builder build --mac zip --arm64 --publish never \
    -c.extraMetadata.version="$CHAIN_VERSION" --config electron-builder.ts

  rm -rf "$CHAIN_FEED_DIR"
  mkdir -p "$CHAIN_FEED_DIR"
  cp "out/PostHog-Desktop-${CHAIN_VERSION}-arm64-mac.zip" "$CHAIN_FEED_DIR/"
  cp "out/PostHog-Desktop-${CHAIN_VERSION}-arm64-mac.zip.blockmap" "$CHAIN_FEED_DIR/"
  cp "out/latest-mac.yml" "$CHAIN_FEED_DIR/"
fi

echo "==> build NEW $NEW_VERSION (feed artifacts)"
pnpm exec electron-builder build --mac zip --arm64 --publish never \
  -c.extraMetadata.version="$NEW_VERSION" --config electron-builder.ts

rm -rf "$FEED_DIR"
mkdir -p "$FEED_DIR"
cp "out/PostHog-Desktop-${NEW_VERSION}-arm64-mac.zip" "$FEED_DIR/"
cp "out/PostHog-Desktop-${NEW_VERSION}-arm64-mac.zip.blockmap" "$FEED_DIR/"
cp "out/latest-mac.yml" "$FEED_DIR/"

echo "==> build OLD $OLD_VERSION (runnable app left in out/mac-arm64)"
pnpm exec electron-builder build --mac zip --arm64 --publish never \
  -c.extraMetadata.version="$OLD_VERSION" --config electron-builder.ts

echo "==> feed=$FEED_DIR"
if [[ -n "$CHAIN_VERSION" ]]; then
  echo "==> chain feed=$CHAIN_FEED_DIR ($CHAIN_VERSION)"
fi
echo "==> app=out/mac-arm64/PostHog.app ($OLD_VERSION)"
