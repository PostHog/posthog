#!/usr/bin/env bash
# Activation steps for the opt-in devenv environment. Each subcommand is one
# devenv task; see the `tasks` block in devenv.nix for how they are wired.
#
# These steps mirror .flox/env/on-activate.sh. Flox runs that hook once per
# activation, while devenv's enterShell runs on every shell entry, so the work
# lives here and devenv decides per task whether to run it. Every subcommand
# must stay idempotent.
#
# IMPORTANT: This script must NEVER use sudo. It runs automatically on shell
# activation, so requiring elevated privileges would condition developers to
# blindly grant root access to code that changes without notice.

set -euo pipefail

ROOT="${DEVENV_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE="${DEVENV_STATE:-$ROOT/.devenv/state}"
VENV="${UV_PROJECT_ENVIRONMENT:-$STATE/venv}"
COMPLETION_DIR="$STATE/completions"

# Sandbox the automatic installs by default on macOS. The build scripts that run
# during an install (uv sdist hooks, allowlisted pnpm builds, cargo build.rs)
# then execute under the same confinement as the dev stack. See bin/dev-sandbox.
sandbox_installs() {
  [[ "$(uname -s)" == "Darwin" ]] || return 1
  [[ -x "$ROOT/bin/dev-sandbox" ]] || return 1
  [[ "${POSTHOG_DEV_SANDBOX:-}" != "0" ]] || return 1
  # .env.local is not loaded yet when tasks run, so read the opt-out from the
  # file directly. Only do that when the live environment says nothing, so a
  # shell export keeps precedence.
  if [[ -z "${POSTHOG_DEV_SANDBOX:-}" ]] &&
    grep -qE "^[[:space:]]*POSTHOG_DEV_SANDBOX=0[[:space:]]*$" "$ROOT/.env.local" 2>/dev/null; then
    return 1
  fi
  return 0
}

# dev-sandbox takes the whole command as a single argument and runs it via
# `bash -c`, so pass it through unsplit.
run_install() {
  local command="$1"
  if sandbox_installs; then
    "$ROOT/bin/dev-sandbox" "$command"
  else
    bash -c "$command"
  fi
}

link_into_venv() {
  local target="$1"
  local name="$2"
  [[ -d "$VENV/bin" ]] || return 0
  [[ -e "$target" ]] || return 0
  ln -sf "$target" "$VENV/bin/$name"
}

# Completions and the man page are conveniences, so a failure here must not fail
# activation.
generate_hogli_docs() {
  [[ -x "$VENV/bin/python" ]] || return 0

  mkdir -p "$COMPLETION_DIR"
  "$VENV/bin/python" -m hogli.completion --shell bash >"$COMPLETION_DIR/hogli.bash" 2>/dev/null || true
  "$VENV/bin/python" -m hogli.completion --shell zsh >"$COMPLETION_DIR/_hogli" 2>/dev/null || true

  local man_dir="$VENV/share/man/man1"
  mkdir -p "$man_dir"
  "$VENV/bin/python" "$ROOT/tools/hogli/scripts/generate_man_page.py" \
    --output "$man_dir/hogli.1" >/dev/null 2>&1 || true
}

task_uv_sync() {
  run_install "uv sync"
  link_into_venv "$ROOT/bin/hogli" hogli
  generate_hogli_docs
}

task_pnpm_install() {
  run_install "pnpm install"
}

task_phrocs_build() {
  make -C "$ROOT/tools/phrocs" build
  link_into_venv "$ROOT/tools/phrocs/dist/phrocs" phrocs
}

# Seed repo-local git settings here, because package.json's postinstall runs
# inside the sandbox, which write-denies .git/config. The postinstall still
# tries blame.ignoreRevsFile for clones that never activate a dev environment
# (.claude/hooks/setup-cloud.sh and friends); under the sandbox that attempt
# no-ops and this one is what lands.
task_git_config() {
  # Idempotent: the --get short-circuits once the value is set.
  git -C "$ROOT" config --get blame.ignoreRevsFile >/dev/null 2>&1 ||
    git -C "$ROOT" config blame.ignoreRevsFile .git-blame-ignore-revs >/dev/null 2>&1 ||
    true
  # Same for husky's core.hooksPath, which `prepare` sets during the sandboxed
  # pnpm install. husky checks only whether git spawned, not how it exited, so
  # the denied write leaves a fresh clone with no hooks and an install that
  # claims success. --local, not --get: a global core.hooksPath would satisfy a
  # merged --get and skip the seed, leaving the repo pointed at the developer's
  # global hooks dir instead.
  git -C "$ROOT" config --local --get core.hooksPath >/dev/null 2>&1 ||
    git -C "$ROOT" config core.hooksPath .husky >/dev/null 2>&1 ||
    true
}

task_hosts_check() {
  local hosts_line="127.0.0.1 db redis7 kafka clickhouse clickhouse-coordinator objectstorage seaweedfs temporal # posthog"
  grep -qF "$hosts_line" /etc/hosts && return 0

  echo "PostHog services need hostnames in /etc/hosts. Copy and run this to update them:"
  echo ""
  echo "  sudo sed -i.bak '/clickhouse-coordinator objectstorage/d' /etc/hosts; echo '${hosts_line}' | sudo tee -a /etc/hosts"
  echo ""
}

# Only creates the file. enterShell loads it, because variables exported from a
# task do not reach the shell unless the task declares them one by one.
task_dotenv() {
  local dotenv="$ROOT/${DOTENV_FILE:-.env}"
  if [[ ! -f "$dotenv" ]] && [[ -f "$ROOT/.env.example" ]]; then
    cp "$ROOT/.env.example" "$dotenv"
  fi
}

case "${1:-}" in
uv-sync) task_uv_sync ;;
pnpm-install) task_pnpm_install ;;
phrocs-build) task_phrocs_build ;;
git-config) task_git_config ;;
hosts-check) task_hosts_check ;;
dotenv) task_dotenv ;;
*)
  echo "usage: $(basename "$0") {uv-sync|pnpm-install|phrocs-build|git-config|hosts-check|dotenv}" >&2
  exit 2
  ;;
esac
