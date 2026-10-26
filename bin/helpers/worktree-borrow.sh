#!/bin/sh
# Functions that let a plain `git worktree add` checkout run lint-staged /
# hogli / ruff / ty without its own node_modules or venv -- by borrowing the
# main clone's, but only when the worktree's lockfiles match the main clone's
# exactly. A mismatch means the worktree's branch changed deps, so borrowing
# would silently run the wrong versions -- callers fall back to today's
# behavior (local install) in that case.
#
# POSIX sh; sourced by the husky hooks and by bin/hogli (bash). Sourcing this
# file has no side effects -- callers invoke the functions below. Never
# `exit`s or `set -e`s since it runs inside the caller's shell.

# Echo the main clone root for the repo root given as $1, or nothing when $1
# is not a linked worktree. Linked worktrees have a `.git` file (pointing at
# the main clone's .git dir), not a `.git` directory.
posthog_main_repo() {
    [ -f "$1/.git" ] || return 0
    _ph_common="$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 0
    _ph_main="$(dirname "$_ph_common")"
    if [ "$_ph_main" != "$1" ]; then
        echo "$_ph_main"
    fi
    return 0
}

# Echo the first venv that exists under the root given as $1, or nothing.
posthog_find_venv() {
    for _ph_venv in "$1/.flox/cache/venv" "$1/.venv" "$1/env"; do
        if [ -d "$_ph_venv" ]; then
            echo "$_ph_venv"
            return 0
        fi
    done
    return 0
}

# Export SSL_CERT_FILE as the system CA bundle, unless a CA file is already
# set. The flox binaries use Nix's OpenSSL, which trusts no CA when neither
# SSL_CERT_FILE nor NIX_SSL_CERT_FILE names a bundle. `flox activate` sets
# them, but a borrow outside an activated shell does not. Without a bundle,
# every TLS request from the borrowed node fails, so pnpm cannot reach the
# registry and the post-checkout install fails. The paths are the bundles on
# macOS, Debian/Ubuntu and RHEL/Fedora.
posthog_export_ca_bundle() {
    if [ -n "${SSL_CERT_FILE:-}" ] || [ -n "${NIX_SSL_CERT_FILE:-}" ]; then
        return 0
    fi
    for _ph_ca in /etc/ssl/cert.pem /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt; do
        if [ -f "$_ph_ca" ]; then
            SSL_CERT_FILE="$_ph_ca"
            export SSL_CERT_FILE
            return 0
        fi
    done
    return 0
}

# Borrow the main clone's toolchain into the current shell's environment.
# Must be called with cwd = repo root (the hooks guarantee that). Scope $1 is
# `node` or `all` (default): post-checkout only needs the node borrow, so it
# skips the venv work (including the uv.lock compare, which isn't free).
posthog_worktree_borrow() {
    _ph_scope="${1:-all}"
    _ph_main="$(posthog_main_repo "$(pwd)")"
    [ -n "$_ph_main" ] || return 0

    # flox-installed pnpm/uv/node live under .flox/run -- add them to PATH so
    # borrowing works even from GUI git clients that don't inherit a
    # flox-activated shell. Prefer the worktree's own flox env, because the
    # main clone's can pin older tools than this worktree's branch requires.
    _ph_flox_root="$_ph_main"
    for _ph_bin in .flox/run/*/bin; do
        if [ -d "$_ph_bin" ]; then
            _ph_flox_root="$(pwd)"
            break
        fi
    done
    if [ -d "$_ph_flox_root/.flox/run" ]; then
        _ph_flox_on_path=""
        for _ph_bin in "$_ph_flox_root/.flox/run"/*/bin; do
            if [ -d "$_ph_bin" ]; then
                PATH="$_ph_bin:$PATH"
                _ph_flox_on_path=1
            fi
        done
        if [ -n "$_ph_flox_on_path" ]; then
            posthog_export_ca_bundle
        fi
    fi

    if [ ! -d node_modules/.pnpm ] && [ -d "$_ph_main/node_modules/.pnpm" ]; then
        if cmp -s pnpm-lock.yaml "$_ph_main/pnpm-lock.yaml"; then
            POSTHOG_BORROW_NODE=1
            PATH="$_ph_main/node_modules/.bin:$PATH"
        else
            echo "worktree: pnpm-lock.yaml differs from $_ph_main, skipping node_modules borrow -- run 'pnpm install --frozen-lockfile --filter=.'" >&2
        fi
    fi

    if [ "$_ph_scope" = "all" ] && [ -z "$(posthog_find_venv "$(pwd)")" ]; then
        _ph_main_venv="$(posthog_find_venv "$_ph_main")"
        if [ -n "$_ph_main_venv" ]; then
            if cmp -s uv.lock "$_ph_main/uv.lock"; then
                VIRTUAL_ENV="$_ph_main_venv"
                export VIRTUAL_ENV
                # uv ignores VIRTUAL_ENV -- UV_PROJECT_ENVIRONMENT is what lets
                # `uv run --no-sync` find the borrowed venv, and UV_NO_SYNC
                # keeps any other `uv run` from resyncing it against this
                # worktree's paths (which would corrupt it for the main clone).
                UV_PROJECT_ENVIRONMENT="$_ph_main_venv"
                export UV_PROJECT_ENVIRONMENT
                UV_NO_SYNC=1
                export UV_NO_SYNC
                PATH="$_ph_main_venv/bin:$PATH"
            else
                echo "worktree: uv.lock differs from $_ph_main, skipping venv borrow -- run 'flox activate'" >&2
            fi
        fi
    fi

    export PATH
    return 0
}
