#!/usr/bin/env bash
# The activation steps that both developer environments run.
# .flox/env/on-activate.sh runs them once per flox activation, and
# bin/devenv-tasks.sh runs them as devenv tasks, so the two environments install
# the same things in the same way.
#
# Sourced by bash callers. Sourcing this file has no side effects: it defines
# functions and two constants. Callers keep their own progress UI and decide
# which steps to run and in which order. Every step must stay idempotent,
# because devenv's enterShell runs on every shell entry.
#
# IMPORTANT: These steps must NEVER use sudo. They run automatically on shell
# activation, so requiring elevated privileges would condition developers to
# blindly grant root access to code that changes without notice.

# The /etc/hosts entry the dev stack needs, and the command that installs it.
# Both activation paths print the same line from here, so they cannot drift.
POSTHOG_HOSTS_LINE="127.0.0.1 db redis7 kafka clickhouse clickhouse-coordinator objectstorage seaweedfs temporal # posthog"
POSTHOG_HOSTS_FIX="sudo sed -i.bak '/clickhouse-coordinator objectstorage/d' /etc/hosts; echo '${POSTHOG_HOSTS_LINE}' | sudo tee -a /etc/hosts"

# flox and devenv export the repo root and the per-project state dir under
# different names, so resolve both here and let each step read one name.
dev_setup_root() {
  printf '%s' "${DEVENV_ROOT:-${FLOX_ENV_PROJECT:-}}"
}

dev_setup_state() {
  printf '%s' "${DEVENV_STATE:-${FLOX_ENV_CACHE:-}}"
}

dev_setup_venv() {
  printf '%s' "${UV_PROJECT_ENVIRONMENT:-$(dev_setup_state)/venv}"
}

# Sandbox the automatic installs by default on macOS. The build scripts that run
# during an install (uv sdist hooks, allowlisted pnpm builds, cargo build.rs)
# then execute under the same confinement as the dev stack. See bin/dev-sandbox.
sandbox_installs() {
  local root
  root="$(dev_setup_root)"
  [[ "$(uname -s)" == "Darwin" ]] || return 1
  [[ -x "$root/bin/dev-sandbox" ]] || return 1
  case "${POSTHOG_DEV_SANDBOX:-}" in
  0)
    return 1
    ;;
  "")
    # .env.local is not loaded yet during activation, so read the opt-out from
    # the file directly. Only do that when the live environment says nothing,
    # so a shell export keeps precedence.
    if grep -qE "^[[:space:]]*POSTHOG_DEV_SANDBOX=0[[:space:]]*$" "$root/.env.local" 2>/dev/null; then
      return 1
    fi
    ;;
  esac
  return 0
}

# dev-sandbox takes the whole command as a single argument and runs it via
# `bash -c`, so pass it through unsplit.
run_install() {
  local command="$1"
  if sandbox_installs; then
    "$(dev_setup_root)/bin/dev-sandbox" "$command"
  else
    bash -c "$command"
  fi
}

link_into_venv() {
  local target="$1"
  local name="$2"
  [[ -d "$(dev_setup_venv)/bin" ]] || return 0
  [[ -e "$target" ]] || return 0
  ln -sf "$target" "$(dev_setup_venv)/bin/$name"
}

# Completions and the man page are conveniences, so a failure here must not fail
# activation.
generate_hogli_docs() {
  local venv
  venv="$(dev_setup_venv)"
  [[ -x "$venv/bin/python" ]] || return 0

  local completion_dir
  completion_dir="$(dev_setup_state)/completions"
  mkdir -p "$completion_dir"
  "$venv/bin/python" -m hogli.completion --shell bash >"$completion_dir/hogli.bash" 2>/dev/null || true
  "$venv/bin/python" -m hogli.completion --shell zsh >"$completion_dir/_hogli" 2>/dev/null || true

  local man_dir="$venv/share/man/man1"
  mkdir -p "$man_dir"
  "$venv/bin/python" "$(dev_setup_root)/tools/hogli/scripts/generate_man_page.py" \
    --output "$man_dir/hogli.1" >/dev/null 2>&1 || true
}

# Expose hogli on PATH and generate its docs. Runs after `uv sync` populated the
# venv, and also on the paths where the install was skipped as up to date.
install_hogli() {
  link_into_venv "$(dev_setup_root)/bin/hogli" hogli
  generate_hogli_docs
}

# The phrocs Makefile tracks every .go file plus go.mod and go.sum, so an
# unchanged tree makes this a no-op.
build_phrocs() {
  make -C "$(dev_setup_root)/tools/phrocs" build
}

# Split from build_phrocs because the venv can appear after the build: callers
# link once the venv exists, including when the build itself was skipped.
link_phrocs() {
  link_into_venv "$(dev_setup_root)/tools/phrocs/dist/phrocs" phrocs
}

# Seed repo-local git settings here, because package.json's postinstall runs
# inside the sandbox, which write-denies .git/config. The postinstall still
# tries blame.ignoreRevsFile for clones that never activate a dev environment
# (.claude/hooks/setup-cloud.sh and friends); under the sandbox that attempt
# no-ops and this one is what lands.
seed_git_config() {
  local root
  root="$(dev_setup_root)"
  # Idempotent: the --get short-circuits once the value is set.
  git -C "$root" config --get blame.ignoreRevsFile >/dev/null 2>&1 ||
    git -C "$root" config blame.ignoreRevsFile .git-blame-ignore-revs >/dev/null 2>&1 ||
    true
  # Same for husky's core.hooksPath, which `prepare` sets during the sandboxed
  # pnpm install. husky checks only whether git spawned, not how it exited, so
  # the denied write leaves a fresh clone with no hooks and an install that
  # claims success. --local, not --get: a global core.hooksPath would satisfy a
  # merged --get and skip the seed, leaving the repo pointed at the developer's
  # global hooks dir instead.
  git -C "$root" config --local --get core.hooksPath >/dev/null 2>&1 ||
    git -C "$root" config core.hooksPath .husky >/dev/null 2>&1 ||
    true
}

hosts_ok() {
  grep -qF "$POSTHOG_HOSTS_LINE" /etc/hosts
}

# Warn only. The fix needs sudo, which activation must never take, so the
# developer runs it themselves.
hosts_check() {
  hosts_ok && return 0

  echo "PostHog services need hostnames in /etc/hosts. Copy and run this to update them:"
  echo ""
  echo "  $POSTHOG_HOSTS_FIX"
  echo ""
  return 0
}

# Only creates the file. Each caller loads it afterwards, because variables
# exported from a devenv task do not reach the shell unless the task declares
# them one by one.
dotenv_create() {
  local root
  root="$(dev_setup_root)"
  local dotenv="$root/${DOTENV_FILE:-.env}"
  if [[ ! -f "$dotenv" ]] && [[ -f "$root/.env.example" ]]; then
    cp "$root/.env.example" "$dotenv"
  fi
}
