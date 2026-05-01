#!/bin/bash
# SessionStart hook: detect Secretive SSH agent for git commit signing.
#
# If SSH_AUTH_SOCK is unset (or still the default macOS launchd agent) and the
# Secretive agent socket exists, point SSH_AUTH_SOCK at it so git commit
# signing works out of the box on macOS.

if [ -z "$CLAUDE_ENV_FILE" ]; then
  exit 0
fi

SECRETIVE_SOCKET="$HOME/Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data/socket.ssh"
if [ -S "$SECRETIVE_SOCKET" ]; then
  # Repoint at Secretive when either:
  #   - SSH_AUTH_SOCK is unset, or
  #   - it points at the default macOS launchd agent AND that agent has no
  #     identities loaded (so we don't stomp on a working custom agent).
  # The launchd socket path varies by how the session was started
  # (/var/run/..., /private/tmp/..., /var/folders/...), so match the suffix
  # rather than a single prefix.
  agent_has_no_identities() {
    # ssh-add -l exits 1 if the agent has no identities, 2 if it can't contact
    # the agent at all. Either means "not a useful agent for signing".
    SSH_AUTH_SOCK="$SSH_AUTH_SOCK" ssh-add -l >/dev/null 2>&1
    local rc=$?
    [ "$rc" -eq 1 ] || [ "$rc" -eq 2 ]
  }
  if [ -z "$SSH_AUTH_SOCK" ] \
    || { [[ "$SSH_AUTH_SOCK" == *com.apple.launchd.*/Listeners ]] && agent_has_no_identities; }; then
    printf 'export SSH_AUTH_SOCK=%q\n' "$SECRETIVE_SOCKET" >> "$CLAUDE_ENV_FILE"
  fi
fi
