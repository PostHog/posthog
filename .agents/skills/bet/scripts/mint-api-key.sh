#!/usr/bin/env bash
# One-time setup: mint a personal API key scoped to exactly what the /bet
# skill needs, and write ~/.config/foundry/bet.env.
#
# Run from the posthog repo root (needs manage.py + a working Django env):
#
#   .claude/skills/bet/scripts/mint-api-key.sh you@example.com
#
# Scopes minted (see references/setup.md for why each is needed):
#   bet:write        - full bet lifecycle (create/fund/verdict/events/status/list);
#                      ":write" also satisfies ":read" checks, so this alone covers GET too.
#   insight:write    - create the optional rollout-KPI insights
#   dashboard:write  - create the optional "Bet: <slug>" KPI dashboard
#   experiment:read  - pull experiment results into `/bet status` / `/bet verdict`
set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Usage: mint-api-key.sh <user-email> [--label LABEL] [--team-id ID] [--out PATH]" >&2
    exit 1
fi

EMAIL="$1"; shift
LABEL="bet skill"
TEAM_ID=""
OUT="$HOME/.config/foundry/bet.env"
while [ $# -gt 0 ]; do
    case "$1" in
        --label) LABEL="$2"; shift 2 ;;
        --team-id) TEAM_ID="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        *) echo "ERROR: unknown argument $1" >&2; exit 1 ;;
    esac
done

if [ ! -f "manage.py" ]; then
    echo "ERROR: run this from the posthog repo root (manage.py not found in $(pwd))." >&2
    exit 1
fi

run_shell() {
    if python manage.py shell -c "$1" 2>/tmp/mint-api-key.stderr; then
        return 0
    fi
    echo "manage.py shell failed directly, retrying under 'flox activate --' ..." >&2
    flox activate -- bash -c "python manage.py shell -c \"$1\""
}

PY_CODE=$(cat <<PYEOF
import json
from posthog.models.user import User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

user = User.objects.get(email="${EMAIL}")
team_id = ${TEAM_ID:-0} or user.teams.order_by("id").first().id
token = generate_random_token_personal()
PersonalAPIKey.objects.create(
    label="${LABEL}",
    user=user,
    secure_value=hash_key_value(token),
    scopes=["bet:write", "insight:write", "dashboard:write", "experiment:read"],
    scoped_teams=[team_id],
)
print("MINT_RESULT:" + json.dumps({"token": token, "team_id": team_id}))
PYEOF
)

OUTPUT="$(run_shell "$PY_CODE")"
RESULT_LINE="$(echo "$OUTPUT" | grep '^MINT_RESULT:' | tail -1)"
if [ -z "$RESULT_LINE" ]; then
    echo "ERROR: could not find a user with email '${EMAIL}', or the shell command failed. Full output:" >&2
    echo "$OUTPUT" >&2
    exit 1
fi

TOKEN=$(echo "${RESULT_LINE#MINT_RESULT:}" | jq -r .token)
MINTED_TEAM_ID=$(echo "${RESULT_LINE#MINT_RESULT:}" | jq -r .team_id)

mkdir -p "$(dirname "$OUT")"
umask 077
cat > "$OUT" <<ENVEOF
POSTHOG_URL=http://localhost:8010
POSTHOG_PROJECT_ID=${MINTED_TEAM_ID}
POSTHOG_PERSONAL_API_KEY=${TOKEN}
ENVEOF

echo "Wrote ${OUT} (mode 600) for team ${MINTED_TEAM_ID}."
echo "Scopes: bet:write, insight:write, dashboard:write, experiment:read"
