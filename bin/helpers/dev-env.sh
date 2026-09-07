#!/bin/sh
# Resolver for the two supported developer environments: flox (the default) and
# the opt-in devenv (devenv.nix). Scripts ask here instead of testing for .flox
# or .devenv themselves, so the layout of each environment is described once.
#
# POSIX sh; sourced by bash and sh callers. Sourcing this file has no side
# effects -- callers invoke the functions below. Never `exit`s or `set -e`s
# since it runs inside the caller's shell.

# Echo `devenv` or `flox`. POSTHOG_DEV_ENV wins in both directions, so a
# developer can force either environment. Without it, an installed devenv
# binary is the opt-in: an activated devenv shell exports DEVENV_ROOT, and a
# shell outside one still has the binary on PATH. .envrc applies the same rule.
posthog_dev_env_kind() {
    case "${POSTHOG_DEV_ENV:-}" in
        devenv | flox)
            echo "$POSTHOG_DEV_ENV"
            return 0
            ;;
    esac
    if [ -n "${DEVENV_ROOT:-}" ] || command -v devenv >/dev/null 2>&1; then
        echo "devenv"
    else
        echo "flox"
    fi
}

# Echo the command that re-enters the selected environment, for hints only.
posthog_dev_env_activate_hint() {
    if [ "$(posthog_dev_env_kind)" = "devenv" ]; then
        echo "devenv shell"
    else
        echo "flox activate"
    fi
}

# Echo the first venv that exists under the root given as $1, or nothing.
# Both environments are tried because the root can belong to another setup: a
# light worktree borrows the main clone's venv, and the main clone may run the
# other environment.
posthog_find_venv() {
    if [ "$(posthog_dev_env_kind)" = "devenv" ]; then
        _ph_first="$1/.devenv/state/venv"
        _ph_second="$1/.flox/cache/venv"
    else
        _ph_first="$1/.flox/cache/venv"
        _ph_second="$1/.devenv/state/venv"
    fi
    for _ph_venv in "$_ph_first" "$_ph_second" "$1/.venv" "$1/env"; do
        if [ -d "$_ph_venv" ]; then
            echo "$_ph_venv"
            return 0
        fi
    done
    return 0
}

_posthog_flox_bin_dirs() {
    [ -d "$1/.flox/run" ] || return 0
    for _ph_bin in "$1/.flox/run"/*/bin; do
        if [ -d "$_ph_bin" ]; then
            echo "$_ph_bin"
        fi
    done
    return 0
}

# Echo the bin dirs that hold the environment-installed tools (node, uv, pnpm
# and friends) under the root given as $1, one per line, best first. devenv
# merges every package into one profile symlink, while flox keeps one store
# path per package group. Both are listed for the reason given above.
posthog_dev_env_bin_dirs() {
    _ph_devenv_bin="$1/.devenv/profile/bin"
    if [ "$(posthog_dev_env_kind)" = "devenv" ]; then
        [ -d "$_ph_devenv_bin" ] && echo "$_ph_devenv_bin"
        _posthog_flox_bin_dirs "$1"
    else
        _posthog_flox_bin_dirs "$1"
        [ -d "$_ph_devenv_bin" ] && echo "$_ph_devenv_bin"
    fi
    return 0
}
