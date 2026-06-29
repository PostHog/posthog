#!/usr/bin/env bash
#
# Refuse to delete historical Django migration files. The full rationale and the
# safe way to retire a table are in the failure message below and in
# docs/published/handbook/engineering/safe-django-migrations.md.
#
# Intentional, reviewed deletions (a product/app move, a revert, a squash) are
# acknowledged in .github/scripts/migration-deletion-allowlist.txt, not by disabling
# this guard.
#
# Modes:
#   --staged   (default) pre-commit: flag staged deletions of migrations that exist
#              on origin/master; branch-local migrations are safe to delete/regenerate.
#   --stdin    CI: read removed file paths (one per line) from stdin. The caller has
#              already confirmed each path is removed relative to the PR base, so every
#              migration among them is historical.
set -euo pipefail

BASE_REF="${BASE_REF:-origin/master}"
ALLOWLIST="${MIGRATION_DELETION_ALLOWLIST:-.github/scripts/migration-deletion-allowlist.txt}"
MODE="${1:---staged}"

# A deletion is acknowledged if its path matches an allowlist entry — an exact path,
# or a directory prefix ending in "/". Reviewers see the entry in the PR diff.
is_allowlisted() {
    [ -f "$ALLOWLIST" ] || return 1
    local path="$1" line
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%%#*}"                       # strip trailing comment
        line="${line#"${line%%[![:space:]]*}"}"  # trim leading whitespace
        line="${line%"${line##*[![:space:]]}"}"  # trim trailing whitespace
        [ -z "$line" ] && continue
        [ "$path" = "$line" ] && return 0
        case "$line" in
            */) case "$path" in "$line"*) return 0 ;; esac ;;
        esac
    done < "$ALLOWLIST"
    return 1
}

case "$MODE" in
    --stdin) files="$(cat)" ;;
    --staged) files="$(git diff --cached --name-only --diff-filter=D --no-renames)" ;;
    *)
        echo "usage: $(basename "$0") [--staged|--stdin]" >&2
        exit 2
        ;;
esac

violations=""
for f in $files; do
    case "$f" in
        # ClickHouse and async migrations are separate systems, not Django migrations.
        */clickhouse/migrations/*|*/async_migrations/migrations/*) continue ;;
        # Django migrations are numbered NNNN_*.py; this also skips __init__.py.
        */migrations/[0-9]*.py) : ;;
        *) continue ;;
    esac
    # Reviewed, intentional deletions (product moves, reverts, squashes) are allowed.
    if is_allowlisted "$f"; then continue; fi
    if [ "$MODE" = "--staged" ]; then
        # Ignore migrations this branch added itself (never merged to master).
        git cat-file -e "${BASE_REF}:${f}" 2>/dev/null || continue
    fi
    violations="${violations}  - ${f}"$'\n'
done

if [ -n "$violations" ]; then
    printf '\nERROR: refusing to delete historical Django migration file(s):\n\n%s\n' "$violations" >&2
    cat >&2 <<'MSG'
Deleting a migration that exists on master does NOT undo a schema change. The table
and its constraints stay in every database where the migration ran, fresh databases
never recreate them, and the Migration Risk Analysis job re-flags it as a phantom new
migration on every open PR that predates the deletion.

To retire a model/table instead:
  1. Remove all usage and the model class. Run makemigrations, then wrap the generated
     DeleteModel in migrations.SeparateDatabaseAndState(state_operations=[...]) so it
     changes Django state only. KEEP this file. Keep the app in INSTALLED_APPS.
  2. Deploy and wait at least one full deploy cycle.
  3. Optionally DROP TABLE later in a NEW RunSQL migration — never by deleting old files.

Full guide: docs/published/handbook/engineering/safe-django-migrations.md
("Dropping Tables", "Removing a whole product or app").

If this deletion is genuinely intentional and reviewed (a product/app move, a revert,
or a squash), acknowledge it by adding the path(s) to
.github/scripts/migration-deletion-allowlist.txt — never by disabling this guard.

Adding migrations is fine; deleting historical ones is not. Deleting a migration your
branch added but never merged to master is allowed (this check ignores it).
MSG
    exit 1
fi
