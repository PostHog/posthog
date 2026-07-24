#!/usr/bin/env bash
set -euo pipefail

ARCH="${ARCH:-x64}"
case "$ARCH" in
  x64)   DOCKER_PLATFORM="linux/amd64" ;;
  arm64) DOCKER_PLATFORM="linux/arm64" ;;
  *) echo "Unsupported ARCH=$ARCH (expected x64 or arm64)" >&2; exit 1 ;;
esac

# Optional builder targets. Without any, all configured targets run (default).
# Accept friendly aliases or electron-builder target names, via repeatable
# --target/--targets flags (comma-separated) or the TARGETS env var.
RAW_TARGETS="${TARGETS:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --target|--targets)
      [ -n "${2-}" ] || { echo "Missing value for $1" >&2; exit 1; }
      RAW_TARGETS="${RAW_TARGETS:+$RAW_TARGETS,}$2"; shift 2 ;;
    --target=*|--targets=*) RAW_TARGETS="${RAW_TARGETS:+$RAW_TARGETS,}${1#*=}"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

MAKE_TARGETS=""
if [ -n "$RAW_TARGETS" ]; then
  IFS=',' read -ra _targets <<< "$RAW_TARGETS"
  for t in "${_targets[@]}"; do
    t="$(echo "$t" | tr '[:upper:]' '[:lower:]' | xargs)" # lowercase + trim
    [ -z "$t" ] && continue
    case "$t" in
      deb)      pkg="deb" ;;
      rpm)      pkg="rpm" ;;
      zip)      pkg="zip" ;;
      appimage) pkg="AppImage" ;;
      *) echo "Unknown target '$t' (expected: deb, rpm, zip, or appimage)" >&2; exit 1 ;;
    esac
    MAKE_TARGETS="${MAKE_TARGETS:+$MAKE_TARGETS }$pkg"
  done
fi

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT_DIR="$REPO_ROOT/apps/code/out"
mkdir -p "$OUT_DIR"

# Capture host commit so the in-container build reflects the real source revision,
# not the throwaway commit we synthesize below for postinstall scripts.
HOST_COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"

# Stream the repo source (no node_modules / build artifacts) into the container
# so node_modules lives on the container's overlayfs, not a slow FUSE bind mount.
# Only the output dir is bind-mounted so artifacts come back to the host.
cd "$REPO_ROOT"
# COPYFILE_DISABLE stops bsdtar from embedding macOS extended attrs as ._ files.
COPYFILE_DISABLE=1 tar -cf - \
  --exclude='./.git' \
  --exclude='./.pnpm-store' \
  --exclude='node_modules' \
  --exclude='.turbo' \
  --exclude='.vite' \
  --exclude='dist' \
  --exclude='out' \
  --exclude='playwright-results' \
  --exclude='._*' \
  --exclude='.DS_Store' \
  . | exec docker run --rm -i \
    --platform "$DOCKER_PLATFORM" \
    --name build-linux \
    -e CI=true \
    -e NODE_OPTIONS="--max-old-space-size=8192" \
    -e NODE_ENV=production \
    -e ARCH="$ARCH" \
    -e BUILD_COMMIT="$HOST_COMMIT" \
    -e MAKE_TARGETS="$MAKE_TARGETS" \
    -v "$OUT_DIR":/out \
    node:22-bookworm bash -lc '
      set -euo pipefail
      trap "rc=\$?; echo >&2; echo \"[build-linux-docker] FAILED (exit \$rc) at line \$LINENO: \$BASH_COMMAND\" >&2; exit \$rc" ERR
      mkdir -p /work && cd /work && tar -xf -
      corepack enable
      apt-get update && apt-get install -y --no-install-recommends \
        libsecret-1-dev fuse libfuse2 ca-certificates git squashfs-tools zsync zip \
        fakeroot rpm
      # Tarball arrived owned by the host uid; tell git not to refuse on uid mismatch.
      git config --global --add safe.directory /work
      # Postinstall scripts call `git rev-parse` — give them a repo to find.
      git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -q -m init
      pnpm install --frozen-lockfile
      pnpm --filter @posthog/electron-trpc build
      pnpm --filter @posthog/platform build
      pnpm --filter @posthog/shared build
      pnpm --filter @posthog/git build
      pnpm --filter @posthog/enricher build
      pnpm --filter @posthog/agent build
      cd apps/code
      pnpm exec electron-vite build
      if [ -n "${MAKE_TARGETS:-}" ]; then
        pnpm exec electron-builder build --linux $MAKE_TARGETS --${ARCH} --config electron-builder.ts
      else
        pnpm exec electron-builder build --linux --${ARCH} --config electron-builder.ts
      fi
      mkdir -p /out
      cp -r out/. /out/
    '
