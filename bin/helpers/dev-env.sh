#!/bin/sh
# Resolver for the two supported developer environments: flox (the default) and
# the opt-in devenv (devenv.nix). Scripts ask here instead of testing for .flox
# or .devenv themselves, so the layout of each environment is described once.
#
# POSIX sh; sourced by bash and sh callers. Sourcing this file has no side
# effects -- callers invoke the functions below. Never `exit`s or `set -e`s
# since it runs inside the caller's shell.

# Succeed when the selected environment is devenv. POSTHOG_DEV_ENV wins in both
# directions, so a developer can force either environment. Without it, an
# installed devenv binary is the opt-in: an activated devenv shell exports
# DEVENV_ROOT, and a shell outside one still has the binary on PATH. .envrc
# applies the same rule.
#
# The PATH probe is memoized in _POSTHOG_DEV_ENV_KIND, so the functions below
# branch on this rather than on `$(posthog_dev_env_kind)`: a command
# substitution runs in a subshell, where the memo would not survive.
posthog_dev_env_is_devenv() {
    case "${POSTHOG_DEV_ENV:-}" in
        devenv) return 0 ;;
        flox) return 1 ;;
    esac
    if [ -z "${_POSTHOG_DEV_ENV_KIND:-}" ]; then
        if [ -n "${DEVENV_ROOT:-}" ] || command -v devenv >/dev/null 2>&1; then
            _POSTHOG_DEV_ENV_KIND=devenv
        else
            _POSTHOG_DEV_ENV_KIND=flox
        fi
    fi
    [ "$_POSTHOG_DEV_ENV_KIND" = "devenv" ]
}

# Echo `devenv` or `flox`, for callers that report the name or run the binary.
posthog_dev_env_kind() {
    if posthog_dev_env_is_devenv; then
        echo "devenv"
    else
        echo "flox"
    fi
}

# Echo the repo root of the active environment, or nothing when neither is
# active. Both environments export it, under different names.
posthog_dev_env_root() {
    echo "${DEVENV_ROOT:-${FLOX_ENV_PROJECT:-}}"
}

# Echo the command that re-enters the selected environment, for hints only.
posthog_dev_env_activate_hint() {
    if posthog_dev_env_is_devenv; then
        echo "devenv shell"
    else
        echo "flox activate"
    fi
}

# Run "$@" inside the selected environment. Not `exec`ed, so the caller keeps
# control and decides what to do with the exit status. `--trust` keeps flox from
# prompting for an environment it considers another user's, which a fresh
# worktree can look like.
posthog_dev_env_run() {
    if posthog_dev_env_is_devenv; then
        devenv shell -- "$@"
    else
        flox activate --trust -- "$@"
    fi
}

# Echo the files that define the selected environment, one per line, relative to
# a repo root. These are the files the worktree helper copies from the main
# clone, and the files the dev sandbox write-denies because the environment
# executes them unsandboxed on every activation.
posthog_dev_env_config_files() {
    if posthog_dev_env_is_devenv; then
        echo "devenv.nix"
        echo "devenv.yaml"
        echo "devenv.lock"
        echo "bin/devenv-tasks.sh"
    else
        echo ".flox/env/manifest.toml"
        echo ".flox/env/on-activate.sh"
    fi
    echo "bin/helpers/dev-setup-steps.sh"
}

# Echo the first venv that exists under the root given as $1, or nothing.
# Both environments are tried because the root can belong to another setup: a
# light worktree borrows the main clone's venv, and the main clone may run the
# other environment.
posthog_find_venv() {
    if posthog_dev_env_is_devenv; then
        set -- "$1/.devenv/state/venv" "$1/.flox/cache/venv" "$1/.venv" "$1/env"
    else
        set -- "$1/.flox/cache/venv" "$1/.devenv/state/venv" "$1/.venv" "$1/env"
    fi
    for _ph_venv in "$@"; do
        if [ -d "$_ph_venv" ]; then
            echo "$_ph_venv"
            return 0
        fi
    done
    return 0
}

# Echo the bin dirs that hold the environment-installed tools (node, uv, pnpm
# and friends) under the root given as $1, one per line, best first. devenv
# merges every package into one profile symlink, while flox keeps one store
# path per package group. Both are listed for the reason given above. An
# unmatched flox glob stays literal and is dropped by the directory test.
posthog_dev_env_bin_dirs() {
    if posthog_dev_env_is_devenv; then
        set -- "$1/.devenv/profile/bin" "$1"/.flox/run/*/bin
    else
        set -- "$1"/.flox/run/*/bin "$1/.devenv/profile/bin"
    fi
    for _ph_bin in "$@"; do
        if [ -d "$_ph_bin" ]; then
            echo "$_ph_bin"
        fi
    done
    return 0
}
