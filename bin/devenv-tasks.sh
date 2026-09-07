#!/usr/bin/env bash
# Task bodies for the opt-in devenv environment. Each subcommand is one devenv
# task; see the `tasks` block in devenv.nix for how they are wired.
#
# The steps themselves live in bin/helpers/dev-setup-steps.sh, which
# .flox/env/on-activate.sh runs too, so both environments keep one copy of each
# step. This file only decides which steps a task runs.

set -euo pipefail

# devenv exports DEVENV_ROOT for every task. The fallback covers a direct run,
# such as the enterShell guards in devenv.nix. Not exported, so it does not tell
# child processes that a devenv shell is active.
DEVENV_ROOT="${DEVENV_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

source "$DEVENV_ROOT/bin/helpers/dev-setup-steps.sh"

case "${1:-}" in
uv-sync)
  run_install "uv sync"
  install_hogli
  ;;
pnpm-install)
  run_install "pnpm install"
  ;;
phrocs-build)
  build_phrocs
  link_phrocs
  ;;
bootstrap)
  seed_git_config
  dotenv_create
  hosts_check
  ;;
*)
  echo "usage: $(basename "$0") {uv-sync|pnpm-install|phrocs-build|bootstrap}" >&2
  exit 2
  ;;
esac
