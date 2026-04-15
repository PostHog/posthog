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
  # Treat empty or default macOS launchd agent as "no custom agent configured"
  if [ -z "$SSH_AUTH_SOCK" ] || [[ "$SSH_AUTH_SOCK" == /var/run/com.apple.launchd.*/Listeners ]]; then
    printf 'export SSH_AUTH_SOCK=%q\n' "$SECRETIVE_SOCKET" >> "$CLAUDE_ENV_FILE"
  fi
fi
