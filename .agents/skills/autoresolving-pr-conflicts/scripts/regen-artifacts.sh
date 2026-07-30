#!/usr/bin/env bash
# Deterministic boundary for artifact regeneration: `export` copies the merged tree
# without git metadata (the remote URL carries the token); `import` copies back only
# generated artifacts, so nothing else a regen container produced can reach the repo.
set -euo pipefail

usage() {
    echo "usage: $0 export <repo_dir> <scratch_dir>" >&2
    echo "       $0 import <scratch_dir> <repo_dir>" >&2
    exit 2
}

cmd=${1:-}
src=${2:-}
dest=${3:-}
[ -n "$cmd" ] && [ -n "$src" ] && [ -n "$dest" ] || usage
[ -d "$src" ] || usage

case "$cmd" in
    export)
        # Refuse a pre-existing destination: a reused tree could keep a file from an
        # earlier PR under an allowed generated path and leak it into this one.
        if [ -e "$dest" ]; then
            echo "refusing export: $dest already exists; use a fresh per-PR directory" >&2
            exit 1
        fi
        mkdir -p "$(dirname "$dest")"
        mkdir "$dest"
        tar -C "$src" --exclude=.git -cf - . | tar -C "$dest" -xf -
        ;;
    import)
        [ -d "$dest" ] || usage
        (
            cd "$src"
            find . -type f \
                \( -name pnpm-lock.yaml -o -name uv.lock \
                -o -path './frontend/src/generated/*' \
                -o -path './products/*/frontend/generated/*' \) -print0
        ) | while IFS= read -r -d '' f; do
            rel=${f#./}
            path=$dest
            old_ifs=$IFS
            IFS=/
            for part in $rel; do
                path="$path/$part"
                if [ -L "$path" ]; then
                    echo "refusing import: $path is a symlink" >&2
                    exit 1
                fi
            done
            IFS=$old_ifs
            mkdir -p "$dest/$(dirname "$rel")"
            cp "$src/$f" "$dest/$rel"
        done
        ;;
    *)
        usage
        ;;
esac
