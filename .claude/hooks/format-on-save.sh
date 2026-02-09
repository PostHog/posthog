#!/bin/bash
set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
    exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

REL_PATH="${FILE_PATH#"$CLAUDE_PROJECT_DIR"/}"

case "$REL_PATH" in
    *.py)
        ./bin/ruff.sh check --fix --quiet "$FILE_PATH" 2>/dev/null || true
        ./bin/ruff.sh format --quiet "$FILE_PATH" 2>/dev/null
        ;;
    nodejs/*.js)
        pnpm --dir nodejs exec eslint --fix "$FILE_PATH" 2>/dev/null || true
        pnpm --dir nodejs exec prettier --write "$FILE_PATH" 2>/dev/null
        ;;
    *.ts|*.tsx|*.js|*.jsx)
        pnpm oxlint --fix --fix-suggestions --quiet "$FILE_PATH" 2>/dev/null || true
        pnpm prettier --write "$FILE_PATH" 2>/dev/null
        ;;
    *.css|*.scss)
        pnpm stylelint --fix --allow-empty-input "$FILE_PATH" 2>/dev/null || true
        pnpm prettier --write "$FILE_PATH" 2>/dev/null
        ;;
    *.md)
        pnpm exec markdownlint-cli2 --config .config/.markdownlint-cli2.jsonc --fix "$FILE_PATH" 2>/dev/null || true
        pnpm exec prettier --write "$FILE_PATH" 2>/dev/null
        ;;
    *.json|*.yaml|*.yml)
        pnpm prettier --write "$FILE_PATH" 2>/dev/null
        ;;
    *.rs)
        rustfmt "$FILE_PATH" 2>/dev/null
        ;;
esac
