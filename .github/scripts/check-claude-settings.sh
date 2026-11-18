#!/usr/bin/env bash
# .claude/settings.json is shared by everyone, so only repo-wide keys may live in it.
# Personal keys (permissions, env, model...) belong in .claude/settings.local.json
# (gitignored). Checked against the git index so the staged version is what counts.
set -euo pipefail

SHARED_KEYS='["$schema", "hooks", "enabledPlugins"]'

personal=$(git show :.claude/settings.json | node -e '
    const shared = JSON.parse(process.argv[1])
    const settings = JSON.parse(require("fs").readFileSync(0, "utf8"))
    console.log(Object.keys(settings).filter((key) => !shared.includes(key)).join(", "))
' "$SHARED_KEYS")

if [ -z "$personal" ]; then
    exit 0
fi

printf '\n\033[31m.claude/settings.json only holds repo-wide keys (%s).\nMove %s to .claude/settings.local.json (gitignored), or add the key to SHARED_KEYS in %s if everyone needs it.\033[0m\n\n' \
    "$SHARED_KEYS" "$personal" "$0" >&2
exit 1
