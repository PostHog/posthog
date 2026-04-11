#!/bin/bash
# Launcher used by the sandbox tmux "claude" window.
#
# On cold boot, python deps take ~15-30s; during that window we show a banner
# and spin on the /tmp/sandbox-python-ready sentinel. Once python is ready,
# every python-family tool (python, ruff, hogli, manage.py) works — the 90%
# of first-session tool calls. pnpm/cargo/migrations may still be running for
# another ~60s, and if any of those fail the tmux status line shows
# "!! SETUP FAILED — see window 1". Claude is live regardless.
set -e
cd /workspace

if [ ! -f /tmp/sandbox-python-ready ]; then
    printf "Sandbox is starting up. Claude will be ready in a moment.\n"
    printf "Press Ctrl-b 1 to watch full setup progress, Ctrl-b 0 to return here.\n\n"
    while [ ! -f /tmp/sandbox-python-ready ]; do
        printf "."
        sleep 0.2
    done
fi

# Clear the screen so claude's first paint isn't polluted by the banner
# (tmux draws unattached windows at 80x24 — repaint after clear).
printf '\033[2J\033[H'
exec claude
