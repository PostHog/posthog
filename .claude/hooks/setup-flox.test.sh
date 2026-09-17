#!/bin/bash
set -euo pipefail

HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/setup-flox.sh"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/project/.flox/cache" "$TEST_DIR/state"

cat > "$TEST_DIR/bin/flox" <<'SH'
#!/bin/bash
case "$1" in
  activation-state)
    [ "$2" = --dir ] && [ "$3" = "$CLAUDE_PROJECT_DIR" ] || exit 2
    [ "${TEST_UNSUPPORTED:-}" != 1 ] || exit 1
    printf '%s\n' "$TEST_STATE_DIR"
    ;;
  activate)
    touch "$TEST_ACTIVATED"
    printf 'DEBUG=1\n'
    ;;
  *) exit 2 ;;
esac
SH
cat > "$TEST_DIR/bin/ps" <<'SH'
#!/bin/bash
[ "$*" = '-p 4242 -o args=' ] || exit 2
if [ "${TEST_PROCESS:-}" = gone ]; then exit 1; fi
printf '%s\n' "${TEST_PROCESS:-/nix/store/example-flox/bin/flox-activations activate --activate-data /tmp/example}"
SH
chmod +x "$TEST_DIR/bin/flox" "$TEST_DIR/bin/ps"

export PATH="$TEST_DIR/bin:$PATH"
export CLAUDE_PROJECT_DIR="$TEST_DIR/project"
export CLAUDE_ENV_FILE="$TEST_DIR/env"
export TEST_STATE_DIR="$TEST_DIR/state"
export TEST_ACTIVATED="$TEST_DIR/activated"
unset CLAUDE_CODE_REMOTE

run_hook() {
  rm -f "$TEST_ACTIVATED" "$CLAUDE_ENV_FILE" "$CLAUDE_PROJECT_DIR/.flox/cache/claude-env-cache"
  /bin/bash "$HOOK" > "$TEST_DIR/output"
}

starting_state='{"version":3,"ready":{"Starting":[4242,{"store_path":"/nix/store/example","timestamp":1}]}}'
printf '%s\n' "$starting_state" > "$TEST_STATE_DIR/state.json"
run_hook
jq -e '.systemMessage | contains("PID 4242") and contains("ps -p 4242") and contains("If it is stuck") and contains("kill 4242") and contains("without the Flox environment")' "$TEST_DIR/output" >/dev/null
[ ! -e "$TEST_ACTIVATED" ] && [ ! -e "$CLAUDE_ENV_FILE" ]
echo 'ok: an existing starter produces a visible warning without waiting on activation'

for state in \
  '{"version":3,"ready":{"True":{}}}' \
  '{"version":4,"ready":{"Starting":[4242,{}]}}' \
  '{"version":3,"ready":{"Starting":[0,{}]}}' \
  '{"version":3,"ready":{"Starting":["4242",{}]}}' \
  '{invalid'; do
  printf '%s\n' "$state" > "$TEST_STATE_DIR/state.json"
  run_hook
  [ -e "$TEST_ACTIVATED" ] && [ ! -s "$TEST_DIR/output" ]
  /bin/bash -c 'source "$1"; [ "$DEBUG" = 1 ]' test "$CLAUDE_ENV_FILE"
done
echo 'ok: ready, unsupported, invalid, and malformed state use normal activation'

printf '%s\n' "$starting_state" > "$TEST_STATE_DIR/state.json"
for TEST_PROCESS in gone '/usr/bin/sleep 60' '/usr/bin/echo /bin/flox-activations activate --activate-data example'; do
  export TEST_PROCESS
  run_hook
  [ -e "$TEST_ACTIVATED" ] && [ ! -s "$TEST_DIR/output" ]
done
unset TEST_PROCESS
echo 'ok: exited or reused process IDs produce no kill suggestion'

export TEST_UNSUPPORTED=1
run_hook
[ -e "$TEST_ACTIVATED" ] && [ ! -s "$TEST_DIR/output" ]
unset TEST_UNSUPPORTED
echo 'ok: older Flox versions use normal activation'

mkdir -p "$CLAUDE_PROJECT_DIR/.flox/env"
printf 'version = 1\n' > "$CLAUDE_PROJECT_DIR/.flox/env/manifest.toml"
export TEST_UNSUPPORTED=1
run_hook
unset TEST_UNSUPPORTED
rm "$TEST_ACTIVATED" "$CLAUDE_ENV_FILE"
/bin/bash "$HOOK" > "$TEST_DIR/output"
[ ! -e "$TEST_ACTIVATED" ] && [ ! -s "$TEST_DIR/output" ]
/bin/bash -c 'source "$1"; [ "$DEBUG" = 1 ]' test "$CLAUDE_ENV_FILE"
echo 'ok: a valid cache remains usable while another Flox process starts'
