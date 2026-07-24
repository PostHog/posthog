#!/usr/bin/env bash
# Build the LAST Electron Forge release (v0.55.132 / cb0ca68db) as the "old"
# side of the Forge -> electron-builder auto-update E2E.
#
# The point of this test is the genuine built-in Squirrel.Mac client that real
# users are running today. That client only exists in a real Forge build, so the
# old app must be built from the pinned Forge commit, not rebuilt with
# electron-builder. We:
#   1. Check the pinned tag out into an isolated git worktree.
#   2. Apply a one-line env seam so the old build asks our local feed instead of
#      update.electronjs.org (POSTHOG_E2E_UPDATE_HOST). Nothing else in the
#      download/verify/swap path changes.
#   3. Force the version to 1.0.0 so the feed's 2.0.0 is strictly greater.
#   4. Build + sign with the SAME identity the new build uses, so the designated
#      requirement Squirrel checks matches and the swap is allowed.
#   5. Allow http to loopback (the built-in autoUpdater uses NSURLSession, which
#      enforces ATS) and re-seal the bundle.
#   6. Copy the signed app to apps/code/out/old-forge for the spec.
#
# Run from anywhere; paths are resolved from this script. Needs the same signing
# env the new build uses (CSC_LINK / CSC_KEY_PASSWORD) and full git history
# (actions/checkout fetch-depth: 0).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"          # apps/code
REPO_ROOT="$(cd "$APP_DIR/../.." && pwd)"

OLD_REF="${OLD_FORGE_REF:-cb0ca68db}"               # v0.55.132, last Forge release
OLD_VERSION="${OLD_VERSION:-1.0.0}"
WORKTREE="${OLD_FORGE_WORKTREE:-$REPO_ROOT/.old-forge-worktree}"
OUT_APP_DIR="$APP_DIR/out/old-forge"
DEST_APP="$OUT_APP_DIR/PostHog Code.app"

export SKIP_NOTARIZE=1
export HUSKY=0

log() { printf '\n==> %s\n' "$*"; }

cleanup_worktree() {
  git -C "$REPO_ROOT" worktree remove --force "$WORKTREE" 2>/dev/null || true
  rm -rf "$WORKTREE"
}

log "old Forge ref: $OLD_REF (version $OLD_VERSION)"

# 1. Isolated worktree at the pinned tag. Separate node_modules + build output,
#    so the current branch checkout is untouched.
cleanup_worktree
git -C "$REPO_ROOT" worktree add --force --detach "$WORKTREE" "$OLD_REF"
trap cleanup_worktree EXIT

# 2. The env seam: SERVER_HOST honours POSTHOG_E2E_UPDATE_HOST.
UPDATES_TS="$WORKTREE/packages/core/src/updates/updates.ts"
[ -f "$UPDATES_TS" ] || { echo "FAIL: $UPDATES_TS not found at $OLD_REF"; exit 1; }
perl -0pi -e 's{SERVER_HOST = "https://update\.electronjs\.org"}{SERVER_HOST = process.env.POSTHOG_E2E_UPDATE_HOST ?? "https://update.electronjs.org"}' "$UPDATES_TS"
grep -q 'POSTHOG_E2E_UPDATE_HOST' "$UPDATES_TS" || { echo "FAIL: env seam not applied to $UPDATES_TS"; exit 1; }
log "env seam applied: $(grep -n 'SERVER_HOST =' "$UPDATES_TS")"

# 3. Force the old version so the feed's 2.0.0 is strictly greater.
node -e 'const f=process.argv[1];const fs=require("fs");const p=JSON.parse(fs.readFileSync(f,"utf8"));p.version=process.argv[2];fs.writeFileSync(f,JSON.stringify(p,null,2)+"\n")' \
  "$WORKTREE/apps/code/package.json" "$OLD_VERSION"
log "forced version: $(node -e 'console.log(require(process.argv[1]).version)' "$WORKTREE/apps/code/package.json")"

# 4. Reuse the fonts the workflow already fetched into the main checkout.
if [ -d "$APP_DIR/assets/fonts/BerkeleyMono" ]; then
  mkdir -p "$WORKTREE/apps/code/assets/fonts"
  ditto "$APP_DIR/assets/fonts/BerkeleyMono" "$WORKTREE/apps/code/assets/fonts/BerkeleyMono"
  log "copied BerkeleyMono fonts into the worktree"
fi

# 5. Signing identity. Forge's osxSign resolves the identity by NAME from a
#    keychain (unlike electron-builder, which consumes CSC_LINK directly), so
#    import the shared cert into a temp keychain and derive the identity name.
if [ -z "${APPLE_CODESIGN_IDENTITY:-}" ] && [ -n "${CSC_LINK:-}" ]; then
  KEYCHAIN="${RUNNER_TEMP:-/tmp}/old-forge-sign.keychain-db"
  KEYCHAIN_PW="old-forge-temp-pw"
  CERT_P12="${RUNNER_TEMP:-/tmp}/old-forge-cert.p12"
  security delete-keychain "$KEYCHAIN" 2>/dev/null || true
  security create-keychain -p "$KEYCHAIN_PW" "$KEYCHAIN"
  security set-keychain-settings -lut 21600 "$KEYCHAIN"
  security unlock-keychain -p "$KEYCHAIN_PW" "$KEYCHAIN"
  echo "$CSC_LINK" | base64 --decode > "$CERT_P12"
  security import "$CERT_P12" -k "$KEYCHAIN" -P "${CSC_KEY_PASSWORD:-}" -T /usr/bin/codesign
  security set-key-partition-list -S apple-tool:,apple: -s -k "$KEYCHAIN_PW" "$KEYCHAIN" >/dev/null
  EXISTING_KEYCHAINS="$(security list-keychains -d user | sed -e 's/"//g' -e 's/^[[:space:]]*//')"
  # shellcheck disable=SC2086
  security list-keychains -d user -s "$KEYCHAIN" $EXISTING_KEYCHAINS
  APPLE_CODESIGN_IDENTITY="$(security find-identity -v -p codesigning "$KEYCHAIN" | sed -n 's/.*"\(.*\)".*/\1/p' | head -1)"
  export APPLE_CODESIGN_IDENTITY
  rm -f "$CERT_P12"
fi
[ -n "${APPLE_CODESIGN_IDENTITY:-}" ] || {
  echo "FAIL: no signing identity. Squirrel only swaps a signed bundle whose"
  echo "      designated requirement matches; set CSC_LINK / CSC_KEY_PASSWORD"
  echo "      or APPLE_CODESIGN_IDENTITY."
  exit 1
}
log "signing identity: $APPLE_CODESIGN_IDENTITY"

# 6. Build + sign the old Forge app (turbo build of deps, then forge package).
cd "$WORKTREE"
log "installing worktree dependencies"
# The old tree may carry a lockfile from an older pnpm; fall back if the current
# pnpm refuses it frozen. The worktree is disposable, so a relaxed install is fine.
pnpm install --frozen-lockfile || pnpm install --no-frozen-lockfile
log "building workspace dependencies"
pnpm build:deps
log "packaging the Forge app"
pnpm --filter code package

BUILT_APP="$WORKTREE/apps/code/out/PostHog Code-darwin-arm64/PostHog Code.app"
[ -d "$BUILT_APP" ] || {
  echo "FAIL: forge package did not produce $BUILT_APP"
  ls -la "$WORKTREE/apps/code/out" 2>/dev/null || true
  exit 1
}

# 7. Allow http to loopback so the built-in autoUpdater (NSURLSession) can reach
#    our local feed, then re-sign the OUTER bundle with the same identity +
#    entitlements. Editing Info.plist invalidates only the outer seal; nested
#    code keeps its valid signatures, so the designated requirement is unchanged.
PLIST="$BUILT_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSAppTransportSecurity dict" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :NSAppTransportSecurity:NSAllowsLocalNetworking bool true" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :NSAppTransportSecurity:NSAllowsLocalNetworking true" "$PLIST"
codesign --force --options runtime --timestamp=none \
  --entitlements "$WORKTREE/apps/code/build/entitlements.mac.plist" \
  --sign "$APPLE_CODESIGN_IDENTITY" "$BUILT_APP"
codesign --verify --strict --verbose=2 "$BUILT_APP"

# 8. Hand the signed app to the location the spec expects.
rm -rf "$OUT_APP_DIR"
mkdir -p "$OUT_APP_DIR"
ditto "$BUILT_APP" "$DEST_APP"

log "old Forge app ready: $DEST_APP"
log "bundle version: $(plutil -extract CFBundleShortVersionString raw "$DEST_APP/Contents/Info.plist")"
