#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT_DIR="$ROOT_DIR/../../posthog/user_scripts"
UDFS=(
    json_drop_keys_udf
    json_clean_posthog_event_properties_udf
    json_strip_empty_strings_and_nulls_udf
)

cd "$ROOT_DIR"
go test ./...

for goarch in amd64 arm64; do
    case "$goarch" in
        amd64) suffix=x86_64 ;;
        arm64) suffix=aarch64 ;;
    esac

    for udf in "${UDFS[@]}"; do
        CGO_ENABLED=0 GOOS=linux GOARCH="$goarch" \
            go build -buildvcs=false -trimpath -ldflags "-s -w" -o "$OUT_DIR/${udf}_${suffix}" "./cmd/$udf"
    done
done
