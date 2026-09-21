#!/bin/sh
# Rebuilds the terminal's framebuffer kernel and fbDOOM. Needs Docker.
# Update the SHA-256 values in terminalRuntime.ts with the printed ones.
set -eu
scripts="$(cd "$(dirname "$0")" && pwd)"
assets="$scripts/../../public/terminal"
docker build -t posthog-terminal-display "$scripts"
docker run --rm -v "$scripts:/scripts:ro" -v "$assets:/out" posthog-terminal-display sh /scripts/build-in-container.sh
