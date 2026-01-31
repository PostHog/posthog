#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT_DIR="$ROOT_DIR/bin"

mkdir -p "$OUT_DIR"

go test ./...

build_target() {
  local arch=$1
  local output="$OUT_DIR/json_drop_keys_udf-linux-$arch"

  CGO_ENABLED=0 GOOS=linux GOARCH="$arch" \
    go build -trimpath -ldflags "-s -w" -o "$output" ./cmd/json_drop_keys_udf

  chmod +x "$output"
}

build_target amd64
build_target arm64

echo "Built binaries in $OUT_DIR"
