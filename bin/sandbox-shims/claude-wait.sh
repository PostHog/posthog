#!/bin/bash
# Launcher used by the sandbox tmux "claude" window.
#
# On cold boot, Python deps aren't ready for a few seconds; during that window
# we show a banner and spin on the /tmp/sandbox-python-ready sentinel. Once
# Python is ready, every Python-family tool (python, ruff, hogli, manage.py)
# works — the 90% of first-session tool calls. pnpm/cargo may still be
# installing for another ~60s; that's an accepted trade-off.
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
