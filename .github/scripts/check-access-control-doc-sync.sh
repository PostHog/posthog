#!/bin/sh
# Warn when a commit touches HogQL access control code without also staging the
# doc that describes it. Never blocks: a script can check that these files
# changed together, not whether behavior actually changed.

DOC="posthog/hogql/ACCESS_CONTROL.md"
[ -f "$DOC" ] || exit 0

# The enforcement core the doc describes. Deliberately excludes big shared files
# (database.py, printer/clickhouse.py) where most edits are unrelated.
CORE_FILES="
posthog/hogql/printer/access_control.py
posthog/hogql/restricted_properties.py
posthog/hogql/transforms/clickhouse_property_resolution.py
posthog/hogql_queries/access_controlled_resources.py
posthog/query_creator_access.py
posthog/rbac/user_access_control.py
posthog/shared_link_user.py
posthog/synthetic_user.py
"
CORE_DIRS="products/access_control/backend/"

STAGED=$(git diff --cached --name-only)
printf '%s\n' "$STAGED" | grep -qx "$DOC" && exit 0

HITS=""
for f in $CORE_FILES; do
    if printf '%s\n' "$STAGED" | grep -qx "$f"; then
        HITS="$HITS    $f
"
    fi
done
# No grep | while read here: the pipeline would run the loop in a subshell and
# lose the HITS accumulation. sed indents inside the substitution instead, which
# also keeps filenames with spaces intact.
for d in $CORE_DIRS; do
    dir_hits=$(printf '%s\n' "$STAGED" | grep "^$d" | sed 's/^/    /')
    [ -n "$dir_hits" ] && HITS="$HITS$dir_hits
"
done
[ -z "$HITS" ] && exit 0

printf '\n\033[33mThis commit changes HogQL access control code documented in %s:\n%sIf the behavior described there changed, update the doc in the same PR.\033[0m\n\n' "$DOC" "$HITS"
exit 0
