#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$REPO_ROOT/packages/personhog-proto"
SOURCE_FILE="$OUT_DIR/PROTO_SOURCE.json"
CURRENT_PROTO_PATH="ingestion/proto/personhog"

# The stubs are generated from the personhog protos at the commit PROTO_SOURCE.json records, so a
# proto change lands on ingestion's side first and Django takes it when it bumps the pin. With
# --bump the pin moves to the protos in the working tree, at the last commit that touched them.
BUMP=0
if [ "${1:-}" = "--bump" ]; then
    BUMP=1
fi

if [ "$BUMP" = "1" ]; then
    PROTO_COMMIT="$(git -C "$REPO_ROOT" log -1 --format=%H -- "$CURRENT_PROTO_PATH")"
    PROTO_PATH="$CURRENT_PROTO_PATH"
    printf '{\n    "commit": "%s",\n    "path": "%s"\n}\n' "$PROTO_COMMIT" "$PROTO_PATH" > "$SOURCE_FILE"
else
    PROTO_COMMIT="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['commit'])" "$SOURCE_FILE")"
    PROTO_PATH="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['path'])" "$SOURCE_FILE")"
fi

# A shallow checkout may not hold the pinned commit; the protos are read from it either way.
if ! git -C "$REPO_ROOT" cat-file -e "$PROTO_COMMIT^{commit}" 2>/dev/null; then
    git -C "$REPO_ROOT" fetch --no-tags --depth=1 origin "$PROTO_COMMIT"
fi
PROTO_ROOT="$(mktemp -d)"
trap 'rm -rf "$PROTO_ROOT"' EXIT
git -C "$REPO_ROOT" archive "$PROTO_COMMIT" "$PROTO_PATH" | tar -x -C "$PROTO_ROOT"
PROTO_DIR="$PROTO_ROOT/$(dirname "$PROTO_PATH")"
echo "Generating from $PROTO_PATH at $PROTO_COMMIT"

python -c "import grpc_tools" 2>/dev/null || { echo "Error: grpcio-tools is not installed. Run: uv sync" >&2; exit 1; }

echo "Cleaning old generated files..."
rm -rf "$OUT_DIR/personhog"

# The facade, the lifecycle sagas and the types they share. Django never talks to the leader or
# the replica directly, and it reaches the identity server only through the lifecycle service, so
# those protos stay out: with no identity stubs the ingestion RPCs cannot be called from Python.
mapfile -d '' PROTO_FILES < <(
    find "$PROTO_DIR/personhog/service" "$PROTO_DIR/personhog/lifecycle" "$PROTO_DIR/personhog/types" \
        -name '*.proto' -print0 | sort -z
)

echo "Generating Python protobuf and gRPC stubs..."
python -m grpc_tools.protoc \
    --proto_path="$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --pyi_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    "${PROTO_FILES[@]}"

# protoc emits no package markers; type checkers and wheel builds want regular packages, and
# PEP 561 needs py.typed before a type checker reads the .pyi stubs of an installed package.
find "$OUT_DIR/personhog" -type d -exec touch {}/__init__.py \;
touch "$OUT_DIR/personhog/py.typed"

echo "Linting and formatting generated files..."
ruff check --fix --quiet "$OUT_DIR"
ruff format --quiet "$OUT_DIR"

echo "Done. Generated files are in $OUT_DIR"
