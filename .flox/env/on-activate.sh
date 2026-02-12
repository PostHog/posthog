#!/usr/bin/env bash
# PostHog flox on-activate hook
# Sourced (not executed) from manifest.toml — env vars persist into profile scripts.

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
    # Show last few lines of output on failure
    echo -e "    ${C_DIM}$(tail -n 3 "$tmpfile" 2>/dev/null)${C_RESET}"
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

# ── Direnv first-time setup (interactive only) ─────────────────────
if [[ -t 0 ]] && ! command -v direnv >/dev/null 2>&1 && [[ ! -f "$FLOX_ENV_CACHE/.hush-direnv" ]]; then
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

# ── Header ──────────────────────────────────────────────────────────
_branch=$(git -C "$FLOX_ENV_PROJECT" branch --show-current 2>/dev/null || echo "???")
echo -e "\n${C_CYAN}PostHog dev${C_RESET} ${C_DIM}── ${_branch}${C_RESET}\n"

_activation_start=$(date +%s)

# ── Step 1: Python packages (must run before hogli — it needs Click) ─
run_step "Python packages" uv sync

# Expose hogli on PATH via the uv-managed venv
if [[ -d "$UV_PROJECT_ENVIRONMENT/bin" ]]; then
  ln -sf "$FLOX_ENV_PROJECT/bin/hogli" "$UV_PROJECT_ENVIRONMENT/bin/hogli"
fi

# Install shell completions for hogli
HOGLI_COMPLETION_DIR="$FLOX_ENV_CACHE/completions"
mkdir -p "$HOGLI_COMPLETION_DIR"
if [[ -d "$UV_PROJECT_ENVIRONMENT/bin" ]]; then
  PYTHONPATH="$FLOX_ENV_PROJECT/common" "$UV_PROJECT_ENVIRONMENT/bin/python" \
    -m hogli.core.completion --shell bash > "$HOGLI_COMPLETION_DIR/hogli.bash" 2>/dev/null || true
  PYTHONPATH="$FLOX_ENV_PROJECT/common" "$UV_PROJECT_ENVIRONMENT/bin/python" \
    -m hogli.core.completion --shell zsh > "$HOGLI_COMPLETION_DIR/_hogli" 2>/dev/null || true
fi

# ── Step 2: Node packages ──────────────────────────────────────────
run_step "Node packages" pnpm install

# ── Step 4: /etc/hosts ──────────────────────────────────────────────
if grep -q "127.0.0.1 kafka clickhouse clickhouse-coordinator objectstorage" /etc/hosts; then
  done_step "System hosts"
else
  echo "127.0.0.1 kafka clickhouse clickhouse-coordinator objectstorage" | sudo tee -a /etc/hosts 1>/dev/null
  done_step "System hosts (updated)"
fi

# ── Step 5: Environment variables ───────────────────────────────────
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

# ── Summary ─────────────────────────────────────────────────────────
_activation_end=$(date +%s)
_activation_time=$(( _activation_end - _activation_start ))
echo -e "\n${C_DIM}Ready in ${_activation_time}s${C_RESET}"

# ── Interactive welcome ─────────────────────────────────────────────
if [[ -t 0 ]]; then
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

${C_ITALIC}Useful processes available in hogli start (mprocs)${C_RESET}
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
${C_DIM}  ${C_BOLD}q${C_RESET}${C_DIM} / ${C_BOLD}r${C_RESET}${C_DIM} in mprocs${C_RESET}             Quit / restart a process
"
fi

# ── Silent background cleanup ──────────────────────────────────────
# Clean old flox log files (>7 days). Fire-and-forget after activation.
(
  if [[ -x "$UV_PROJECT_ENVIRONMENT/bin/python" && -f "$FLOX_ENV_PROJECT/bin/hogli" ]]; then
    PYTHONPATH="$FLOX_ENV_PROJECT/common" "$UV_PROJECT_ENVIRONMENT/bin/python" \
      -m hogli.core doctor:disk --area=flox-logs --yes >/dev/null 2>&1
  else
    find "$FLOX_ENV_PROJECT/.flox/log" -name "*.log" -type f -mtime +7 -delete 2>/dev/null
  fi
) &
disown
