#!/usr/bin/env bash
# PostHog flox on-activate hook
# Sourced (not executed) from manifest.toml — env vars persist into profile scripts.
#
# IMPORTANT: This script must NEVER use sudo. It runs automatically on every
# shell activation, so requiring elevated privileges would condition developers
# to blindly grant root access to code that changes without notice.

set -euo pipefail

# ── Colors & symbols ────────────────────────────────────────────────
readonly C_RESET='\033[0m'
readonly C_DIM='\033[2m'
readonly C_GREEN='\033[32m'
readonly C_YELLOW='\033[33m'
readonly C_RED='\033[31m'
readonly C_CYAN='\033[1;36m'
readonly C_ITALIC='\033[3m'
readonly C_BOLD='\033[1m'
readonly SPINNER_FRAMES=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')

_ACTIVATION_TMPFILES=()
_cleanup_tmpfiles() {
  for f in "${_ACTIVATION_TMPFILES[@]}"; do
    rm -f "$f" 2>/dev/null
  done
}
trap _cleanup_tmpfiles EXIT

_strip_ansi() {
  sed $'s/\x1b\\[[0-9;]*[a-zA-Z]//g' | tr -d '\r'
}

_save_failure_log() {
  local label="$1"
  local tmpfile="$2"
  local logdir="$FLOX_ENV_CACHE/activation-error-logs"
  local slug="${label// /-}"
  local logfile="$logdir/${slug}-$(date +%Y%m%d-%H%M%S).log"

  local log_saved=0
  # Best-effort: failures here must not abort the script under `set -euo pipefail`.
  if mkdir -p "$logdir" 2>/dev/null; then
    {
      echo "── ${label} (failed) ──"
      _strip_ansi < "$tmpfile"
      echo ""
    } 2>/dev/null > "$logfile" && log_saved=1 || true
  fi

  printf '    %b%s%b\n' "${C_DIM}" "$(tail -n 15 "$tmpfile" 2>/dev/null | _strip_ansi || true)" "${C_RESET}"
  if [[ "$log_saved" -eq 1 ]]; then
    printf '    %bFull log: %s%b\n' "${C_DIM}" "$logfile" "${C_RESET}"
  fi
}

# ── Step runner ─────────────────────────────────────────────────────
# Runs a command with a spinner and live output preview.
# Usage: run_step "Label" command [args...]
#   - Shows a braille spinner with elapsed time while the command runs.
#   - Below the spinner line, the last line of command output scrolls in-place.
#   - On completion, collapses to a single "✓ Label  Ns" or "✗ Label  Ns" line.
#   - Non-interactive: falls back to a simple "... Label" / "✓ Label" pair.
run_step() {
  local label="$1"
  shift

  local tmpfile
  tmpfile=$(mktemp)
  _ACTIVATION_TMPFILES+=("$tmpfile")

  local start_time
  start_time=$(date +%s)

  # Non-interactive fallback
  if [[ ! -t 1 ]]; then
    echo -ne "  ... ${label}"
    if "$@" > "$tmpfile" 2>&1; then
      echo -e "\r  ${C_GREEN}✓${C_RESET} ${label}"
    else
      echo -e "\r  ${C_RED}✗${C_RESET} ${label}  (failed)"
      _save_failure_log "$label" "$tmpfile"
      return 1
    fi
    return 0
  fi

  # Run command in background
  "$@" > "$tmpfile" 2>&1 &
  local pid=$!

  local frame=0
  local had_output=false

  # Spinner loop
  while kill -0 "$pid" 2>/dev/null; do
    local elapsed=$(( $(date +%s) - start_time ))
    local ch="${SPINNER_FRAMES[$(( frame % ${#SPINNER_FRAMES[@]} ))]}"

    # Read last non-empty line from output
    local last_line=""
    if [[ -s "$tmpfile" ]]; then
      last_line=$(tail -n 1 "$tmpfile" 2>/dev/null | tr -d '\r' | cut -c1-70)
    fi

    # Redraw: clear previous output line if we had one
    if [[ "$had_output" == true ]]; then
      echo -ne "\033[A\033[2K"  # up one, clear line
    fi
    # Clear spinner line and redraw
    printf "\r\033[2K  ${C_YELLOW}%s${C_RESET} %-42s %3ds" "$ch" "$label" "$elapsed"

    # Show output preview below spinner
    if [[ -n "$last_line" ]]; then
      printf "\n    ${C_DIM}%s${C_RESET}" "$last_line"
      had_output=true
    else
      had_output=false
    fi

    frame=$(( frame + 1 ))
    sleep 0.08
  done

  local exit_code=0
  wait "$pid" 2>/dev/null || exit_code=$?
  local elapsed=$(( $(date +%s) - start_time ))

  # Clear output preview line
  if [[ "$had_output" == true ]]; then
    echo -ne "\033[A\033[2K"
  fi

  # Final status line
  if [[ $exit_code -eq 0 ]]; then
    printf "\r\033[2K  ${C_GREEN}✓${C_RESET} %-42s %3ds\n" "$label" "$elapsed"
    # Clear the line below (old output preview may linger)
    if [[ "$had_output" == true ]]; then printf "\033[2K"; fi
  else
    printf "\r\033[2K  ${C_RED}✗${C_RESET} %-42s %3ds\n" "$label" "$elapsed"
    # Save failure log and show last few lines of output on failure
    _save_failure_log "$label" "$tmpfile"
    return $exit_code
  fi
}

# Compute sha256 of a file. Portable across Linux (sha256sum) and macOS
# (shasum). Returns empty string when the file is missing or no hasher
# is available; safe to call inside `[[ ... ]]` under set -euo pipefail.
_sha256_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  local result=""
  if command -v sha256sum >/dev/null 2>&1; then
    result=$(sha256sum "$file" 2>/dev/null | awk '{print $1}' || true)
  elif command -v shasum >/dev/null 2>&1; then
    result=$(shasum -a 256 "$file" 2>/dev/null | awk '{print $1}' || true)
  fi
  printf '%s' "$result"
}

# Read an AMI-bake stamp file, stripping whitespace. Returns empty
# string when the stamp is missing -- which is the expected case on
# laptops and on workspaces booted from a non-baked image. Callers
# treat empty as "no match" and fall back to running the full step.
_read_ami_stamp() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  tr -d '[:space:]' < "$file" 2>/dev/null || true
}

# Waits for a step that was started earlier as a background subshell and
# reports its outcome. Mirrors run_step's final status line without a
# spinner -- the work has usually completed by the time wait is called.
# Usage: wait_bg_step "Label" <pid> <start_epoch> <logfile>
wait_bg_step() {
  local label="$1"
  local pid="$2"
  local start_time="$3"
  local tmpfile="$4"

  local exit_code=0
  wait "$pid" 2>/dev/null || exit_code=$?
  local elapsed=$(( $(date +%s) - start_time ))

  if [[ $exit_code -eq 0 ]]; then
    printf "  ${C_GREEN}✓${C_RESET} %-42s %3ds\n" "$label" "$elapsed"
  else
    printf "  ${C_RED}✗${C_RESET} %-42s %3ds\n" "$label" "$elapsed"
    _save_failure_log "$label" "$tmpfile"
    return $exit_code
  fi
}

# Inline step (instant, no spinner)
done_step() {
  local label="$1"
  printf "  ${C_GREEN}✓${C_RESET} %s\n" "$label"
}

warn_step() {
  local label="$1"
  printf "  ${C_YELLOW}⚠${C_RESET} %s\n" "$label"
}

# ── Interactive mode detection ────────────────────────────────────
# Skip all interactive prompts in non-interactive terminals or when running under PostHog Code (automated agent).
_interactive=false
if [[ -t 0 ]] && [[ -z "${POSTHOG_CODE:-}" ]]; then
  _interactive=true
fi

# ── Go toolchain isolation ─────────────────────────────────────────
# User shells often export GOROOT/GOCACHE for Homebrew, asdf, or other local Go
# installs. Keep flox builds on the pinned Go toolchain and cache compiled
# packages inside the flox environment so host Go upgrades cannot poison builds.
unset GOROOT
export GOTOOLCHAIN=local
export GOPATH="$FLOX_ENV_CACHE/go"
export GOCACHE="$FLOX_ENV_CACHE/go-build"
export GOMODCACHE="$GOPATH/pkg/mod"

# uv-managed venv location (mirrors the [profile] scripts; not in [vars], which
# can't expand $FLOX_ENV_CACHE). Used below for uv sync + the hogli symlink.
export UV_PROJECT_ENVIRONMENT="$FLOX_ENV_CACHE/venv"

# ── Direnv first-time setup (interactive only) ─────────────────────
if [[ "$_interactive" == true ]] && ! command -v direnv >/dev/null 2>&1 && [[ ! -f "$FLOX_ENV_CACHE/.hush-direnv" ]]; then
  read -p "$(echo -e "${C_BOLD}direnv${C_RESET} recommended for auto-activation. Set up now? (Y/n) ")" -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ || -z $REPLY ]]; then
    "$FLOX_ENV_CACHE/../env/direnv-setup.sh"
  else
    echo -e "${C_DIM}Skipped. Run '.flox/env/direnv-setup.sh' later if you change your mind.${C_RESET}"
  fi
  touch "$FLOX_ENV_CACHE/.hush-direnv"
  echo
fi

# ── Xcode license check (macOS only) ─────────────────────────────────
# Only check when full Xcode.app is installed (not just Command Line Tools),
# since xcodebuild -license check returns non-zero for CLT-only setups too.
if [[ "$(uname -s)" == "Darwin" ]] && command -v xcodebuild >/dev/null 2>&1 \
   && [[ "$(xcode-select -p 2>/dev/null)" == /Applications/Xcode*.app/* ]]; then
  if ! xcodebuild -license check >/dev/null 2>&1; then
    if [[ "$_interactive" == true ]] && [[ ! -f "$FLOX_ENV_CACHE/.hush-xcode-license" ]]; then
      warn_step "Xcode license not accepted. Native builds may fail."
      read -p "$(echo -e "   Accept Xcode license now? (Y/n) ")" -n 1 -r
      echo
      if [[ $REPLY =~ ^[Yy]$ || -z $REPLY ]]; then
        echo -e "   ${C_DIM}Running: sudo xcodebuild -license accept${C_RESET}"
        if sudo xcodebuild -license accept; then
          done_step "Xcode license accepted"
        else
          echo -e "   ${C_RED}✗${C_RESET} Failed to accept Xcode license"
          echo -e "   ${C_DIM}Run 'sudo xcodebuild -license' manually to resolve.${C_RESET}"
        fi
      else
        touch "$FLOX_ENV_CACHE/.hush-xcode-license"
        echo -e "   ${C_DIM}Skipped. Run 'sudo xcodebuild -license' if builds fail.${C_RESET}"
      fi
      echo
    elif [[ ! -t 0 ]]; then
      echo -e "  ${C_YELLOW}⚠${C_RESET} Xcode license not accepted  ${C_DIM}(run 'sudo xcodebuild -license')${C_RESET}"
    fi
  fi
fi

# ── Header ──────────────────────────────────────────────────────────
_branch=$(git -C "$FLOX_ENV_PROJECT" branch --show-current 2>/dev/null || echo "???")
echo -e "\n${C_CYAN}PostHog dev${C_RESET} ${C_DIM}── ${_branch}${C_RESET}\n"

_activation_start=$(date +%s)

# ── Steps 1, 1b, 2 (kicked off in parallel, with AMI cache-skip) ───
# uv sync, pnpm install, and `make phrocs build` are independent -- none
# of them reads or writes the other's outputs. Kick the two non-spinner
# ones off in the background BEFORE foregrounding uv sync, so the wall
# clock is bounded by the slowest single step instead of the sum. uv sync
# stays foregrounded because the completion + man-page steps that follow
# depend on the venv it populates, and because its run_step spinner remains
# the user-visible progress indicator for activate.
#
# Each step also checks an AMI-bake stamp file (sha256 of the source-of-
# truth input recorded at bake time): when the on-disk hash matches the
# baked hash, the workspace is in the same state as the bake and the
# subprocess would be a no-op, so we skip it entirely. On laptops or
# pre-stamp workspaces the stamps are missing and the checks fall back
# to running normally -- no regression.
_PNPM_LOCK="$FLOX_ENV_PROJECT/pnpm-lock.yaml"
_UV_LOCK="$FLOX_ENV_PROJECT/uv.lock"
_PHROCS_BIN="$FLOX_ENV_PROJECT/tools/phrocs/dist/phrocs"

_PNPM_BAKED=$(_read_ami_stamp /etc/posthog-coder-ami-pnpm-stamp)
_UV_BAKED=$(_read_ami_stamp /etc/posthog-coder-ami-uv-stamp)
_PHROCS_BAKED=$(_read_ami_stamp /etc/posthog-coder-ami-phrocs-stamp)

_PNPM_CURRENT=$(_sha256_file "$_PNPM_LOCK")
_UV_CURRENT=$(_sha256_file "$_UV_LOCK")
_PHROCS_CURRENT=$(_sha256_file "$_PHROCS_BIN")

_PNPM_SKIP=0
[[ -n "$_PNPM_BAKED" && -n "$_PNPM_CURRENT" && "$_PNPM_BAKED" == "$_PNPM_CURRENT" ]] && _PNPM_SKIP=1
_UV_SKIP=0
[[ -n "$_UV_BAKED" && -n "$_UV_CURRENT" && "$_UV_BAKED" == "$_UV_CURRENT" ]] && _UV_SKIP=1
_PHROCS_SKIP=0
[[ -n "$_PHROCS_BAKED" && -n "$_PHROCS_CURRENT" && "$_PHROCS_BAKED" == "$_PHROCS_CURRENT" ]] && _PHROCS_SKIP=1

# Sandbox the automatic installs below by default on macOS (opt out with
# POSTHOG_DEV_SANDBOX=0). .env.local isn't loaded at flox-activate time, so check
# it directly — but only when the live env is unset, so shell env keeps precedence.
# The build scripts that run during install (uv sdist hooks, allowlisted pnpm
# builds, cargo build.rs) then execute inside the sandbox, like the runtime path.
# See bin/dev-sandbox.
_DEV_SANDBOX_INSTALLS=0
if [[ "$(uname -s)" == "Darwin" && -x "$FLOX_ENV_PROJECT/bin/dev-sandbox" ]]; then
  _DEV_SANDBOX_INSTALLS=1
  if [[ "${POSTHOG_DEV_SANDBOX:-}" == "0" ]]; then
    _DEV_SANDBOX_INSTALLS=0
  elif [[ -z "${POSTHOG_DEV_SANDBOX:-}" ]] && grep -qE "^[[:space:]]*POSTHOG_DEV_SANDBOX=0[[:space:]]*$" "$FLOX_ENV_PROJECT/.env.local" 2>/dev/null; then
    _DEV_SANDBOX_INSTALLS=0
  fi
fi

if [[ "$_PNPM_SKIP" -eq 0 ]]; then
  _BG_PNPM_LOG=$(mktemp)
  _ACTIVATION_TMPFILES+=("$_BG_PNPM_LOG")
  if [[ "$_DEV_SANDBOX_INSTALLS" -eq 1 ]]; then
    ( "$FLOX_ENV_PROJECT/bin/dev-sandbox" "pnpm install" ) >"$_BG_PNPM_LOG" 2>&1 &
  else
    ( pnpm install ) >"$_BG_PNPM_LOG" 2>&1 &
  fi
  _BG_PNPM_PID=$!
  _BG_PNPM_START=$(date +%s)
fi

if [[ "$_PHROCS_SKIP" -eq 0 ]]; then
  _BG_PHROCS_LOG=$(mktemp)
  _ACTIVATION_TMPFILES+=("$_BG_PHROCS_LOG")
  ( make -C "$FLOX_ENV_PROJECT/tools/phrocs" build ) >"$_BG_PHROCS_LOG" 2>&1 &
  _BG_PHROCS_PID=$!
  _BG_PHROCS_START=$(date +%s)
fi

# ── Step 1: Python packages (must run before hogli — it needs Click) ─
if [[ "$_UV_SKIP" -eq 1 ]]; then
  done_step "Python packages (cached)"
elif [[ "$_DEV_SANDBOX_INSTALLS" -eq 1 ]]; then
  run_step "Python packages" "$FLOX_ENV_PROJECT/bin/dev-sandbox" "uv sync"
else
  run_step "Python packages" uv sync
fi

# Expose hogli on PATH via the uv-managed venv
if [[ -d "$UV_PROJECT_ENVIRONMENT/bin" ]]; then
  ln -sf "$FLOX_ENV_PROJECT/bin/hogli" "$UV_PROJECT_ENVIRONMENT/bin/hogli"
fi

# Install shell completions for hogli
HOGLI_COMPLETION_DIR="$FLOX_ENV_CACHE/completions"
mkdir -p "$HOGLI_COMPLETION_DIR"
if [[ -d "$UV_PROJECT_ENVIRONMENT/bin" ]]; then
  "$UV_PROJECT_ENVIRONMENT/bin/python" \
    -m hogli.completion --shell bash > "$HOGLI_COMPLETION_DIR/hogli.bash" 2>/dev/null || true
  "$UV_PROJECT_ENVIRONMENT/bin/python" \
    -m hogli.completion --shell zsh > "$HOGLI_COMPLETION_DIR/_hogli" 2>/dev/null || true
fi

# Generate hogli man page into the active environment so `man hogli` works.
HOGLI_MANPAGE_DIR="$UV_PROJECT_ENVIRONMENT/share/man/man1"
if [[ -d "$UV_PROJECT_ENVIRONMENT/bin" ]]; then
  (
    mkdir -p "$HOGLI_MANPAGE_DIR"
    "$UV_PROJECT_ENVIRONMENT/bin/python" \
      "$FLOX_ENV_PROJECT/tools/hogli/scripts/generate_man_page.py" \
      --output "$HOGLI_MANPAGE_DIR/hogli.1" >/dev/null 2>&1
  ) || true
fi

# ── Step 1b: Build phrocs from source ─────────────────────────────
if [[ "$_PHROCS_SKIP" -eq 1 ]]; then
  done_step "Build phrocs (cached)"
else
  wait_bg_step "Build phrocs" "$_BG_PHROCS_PID" "$_BG_PHROCS_START" "$_BG_PHROCS_LOG"
fi
if [[ -f "$FLOX_ENV_PROJECT/tools/phrocs/dist/phrocs" && -d "$UV_PROJECT_ENVIRONMENT/bin" ]]; then
  ln -sf "$FLOX_ENV_PROJECT/tools/phrocs/dist/phrocs" "$UV_PROJECT_ENVIRONMENT/bin/phrocs"
fi

# ── Step 2: Node packages ──────────────────────────────────────────
if [[ "$_PNPM_SKIP" -eq 1 ]]; then
  done_step "Node packages (cached)"
else
  wait_bg_step "Node packages" "$_BG_PNPM_PID" "$_BG_PNPM_START" "$_BG_PNPM_LOG"
fi

# ── Step 3: /etc/hosts ──────────────────────────────────────────────
POSTHOG_HOSTS="127.0.0.1 db redis7 kafka clickhouse clickhouse-coordinator objectstorage seaweedfs temporal # posthog"
if grep -qF "$POSTHOG_HOSTS" /etc/hosts; then
  done_step "System hosts"
else
  echo ""
  echo -e "  ${C_YELLOW}┃${C_RESET} ${C_YELLOW}${C_BOLD}Action required${C_RESET}"
  echo -e "  ${C_YELLOW}┃${C_RESET}"
  echo -e "  ${C_YELLOW}┃${C_RESET} PostHog services need hostnames in /etc/hosts."
  echo -e "  ${C_YELLOW}┃${C_RESET} Copy and run this to update them:"
  echo -e "  ${C_YELLOW}┃${C_RESET}"
  echo -e "  ${C_YELLOW}┃${C_RESET}   ${C_DIM}sudo sed -i.bak '/clickhouse-coordinator objectstorage/d' /etc/hosts; echo '${POSTHOG_HOSTS}' | sudo tee -a /etc/hosts${C_RESET}"
  echo -e "  ${C_YELLOW}┃${C_RESET}"
  echo ""
  if [[ "$_interactive" == true ]]; then
    read -n 1 -s -r -p "  Press any key to continue..."
    echo ""
  fi
fi

# ── Step 4: Environment variables ───────────────────────────────────
if [[ ! -f "$DOTENV_FILE" ]] && [[ -f ".env.example" ]]; then
  cp .env.example "$DOTENV_FILE"
fi
if [[ -f "$DOTENV_FILE" ]]; then
  set -o allexport
  # shellcheck disable=SC1090
  source "$DOTENV_FILE"
  set +o allexport
  done_step "Environment vars"
else
  warn_step "Environment vars  ${C_DIM}(.env not found)${C_RESET}"
fi

# ── Step 5: Rust toolchain check ───────────────────────────────────
_flox_rustc_ver=$(rustc --version 2>/dev/null | awk '{print $2}')
_rustup_rustc="$HOME/.cargo/bin/rustc"
if [[ -x "$_rustup_rustc" ]] && [[ -n "$_flox_rustc_ver" ]]; then
  _rustup_rustc_ver=$("$_rustup_rustc" --version 2>/dev/null | awk '{print $2}')
  if [[ -n "$_rustup_rustc_ver" ]] && [[ "$_flox_rustc_ver" != "$_rustup_rustc_ver" ]]; then
    warn_step "Rust toolchain mismatch: flox has rustc ${_flox_rustc_ver}, rustup has ${_rustup_rustc_ver}"
    echo -e "    ${C_DIM}Building outside flox will use a different compiler and invalidate the entire cargo cache.${C_RESET}"
    echo -e "    ${C_DIM}Fix: ${C_BOLD}rustup toolchain remove stable${C_RESET}${C_DIM} or always build inside flox.${C_RESET}"
  else
    done_step "Rust toolchain (rustc ${_flox_rustc_ver})"
  fi
elif [[ -n "$_flox_rustc_ver" ]]; then
  done_step "Rust toolchain (rustc ${_flox_rustc_ver})"
fi

# Share a single Cargo target dir so worktrees skip redundant linking
export CARGO_TARGET_DIR="$HOME/.cargo/target"

# ── Summary ─────────────────────────────────────────────────────────
_activation_end=$(date +%s)
_activation_time=$(( _activation_end - _activation_start ))
echo -e "\n${C_DIM}Ready in ${_activation_time}s${C_RESET}"

# ── Interactive welcome ─────────────────────────────────────────────
if [[ "$_interactive" == true ]]; then
  quotes=(
    "At PostHog, we don't follow trends, we set them, like records."
    "Be bold, be fearless, and let's lead the way in tech innovation with beast mode."
    "The future belongs to the bold and the strong."
    "Break the mold, push the limits, and let's redefine what's possible with beast mode on."
    "Our best feature? Still in the pipeline."
    "Mindset matters. Stay positive, stay resilient, and keep grinding."
    "Challenges are just opportunities in disguise."
    "Ownership isn't a task, it's a mindset."
  )

  echo -e "\n${C_DIM}─────────────────────────────────────────────────────────${C_RESET}"
  echo -e "${C_ITALIC}${C_DIM}\"${quotes[$RANDOM % ${#quotes[@]}]}\"${C_RESET}"
  echo -e "${C_DIM}  — James Hawkins (probably)${C_RESET}"
  echo -e "${C_DIM}─────────────────────────────────────────────────────────${C_RESET}"

  echo -e "
${C_ITALIC}You're all set! Here's what you can do:${C_RESET}

${C_GREEN}Start the development environment:${C_RESET}
${C_GREEN}${C_BOLD}hogli start${C_RESET}

${C_DIM}Interactive wizard to configure which services to run:${C_RESET}
${C_GREEN}hogli dev:setup${C_RESET}

${C_ITALIC}Useful processes available in hogli start (phrocs)${C_RESET}
${C_DIM}  press ${C_BOLD}r${C_RESET}${C_DIM} to start manually:${C_RESET}
${C_DIM}  generate-demo-data${C_RESET}          Create a user with demo data
${C_DIM}  storybook${C_RESET}                   Run storybook locally
${C_DIM}  hedgebox-dummy${C_RESET}              Demo environment using your local stack

${C_DIM}─────────────────────────────────────────────────────────${C_RESET}

${C_ITALIC}Tips:${C_RESET}
${C_DIM}  hogli --help${C_RESET}                Browse all available commands
${C_DIM}  hogli migrations:run${C_RESET}        Run pending migrations
${C_DIM}  hogli dev:reset${C_RESET}             Wipe volumes, migrate, load demo data
${C_DIM}  hogli doctor:disk${C_RESET}           Free up disk space from dev bloat
${C_DIM}  ${C_BOLD}q${C_RESET}${C_DIM} / ${C_BOLD}r${C_RESET}${C_DIM} in phrocs${C_RESET}             Quit / restart a process
"
fi

# ── Silent background cleanup ──────────────────────────────────────
# Clean old flox log files (>7 days). Fire-and-forget after activation.
(
  if [[ -x "$UV_PROJECT_ENVIRONMENT/bin/python" && -f "$FLOX_ENV_PROJECT/bin/hogli" ]]; then
    POSTHOG_TELEMETRY_OPT_OUT=1 "$UV_PROJECT_ENVIRONMENT/bin/python" \
      -m hogli doctor:disk --area=flox-logs --yes >/dev/null 2>&1
  else
    find "$FLOX_ENV_PROJECT/.flox/log" -name "*.log" -type f -mtime +7 -delete 2>/dev/null
  fi
) &
disown
