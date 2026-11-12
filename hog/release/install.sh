#!/bin/sh
# shellcheck disable=SC2006
echo `# <#` >/dev/null
# Installs hog, the PostHog command line, on macOS and Linux.
#
# The line above opens a PowerShell block comment, which the marker after `exit` at the end closes.
# So `irm .../install.sh | iex` in PowerShell skips the sh code and prints the right command instead
# of parse errors. Nothing above that marker may contain it, or PowerShell reads sh code.
#
#   curl -fsSL https://releases.posthog.com/hog/install.sh | sh
#   curl -fsSL https://releases.posthog.com/hog/install.sh | sh -s -- --version 1.2.3
#
# Options, each with an environment variable:
#   --version <version>   HOG_VERSION       Install this version instead of the latest one
#   --dir <folder>        HOG_INSTALL_DIR   Where to put the binary. Defaults to ~/.local/bin
#
# Everything runs from main, called on the last line, so a download cut short runs nothing.

set -eu

HOG_RELEASES_URL="${HOG_RELEASES_URL:-https://releases.posthog.com/hog}"
HOG_MIRROR_URL="${HOG_MIRROR_URL:-https://github.com/PostHog/posthog/releases/download}"

say() {
    printf '%s\n' "$*"
}

err() {
    printf 'hog install: %s\n' "$*" >&2
    exit 1
}

has() {
    command -v "$1" >/dev/null 2>&1
}

# Downloads $1 to $2. Only https leaves the machine, unless HOG_RELEASES_URL points elsewhere on purpose.
# `--retry` covers timeouts and 5xx answers but not a 404, so a missing file falls back at once.
# A third argument of `quiet` hides curl's error, for a download that has a fallback.
download() {
    case "$1" in
        https://*) proto='=https' ;;
        *) proto='=https,http,file' ;;
    esac
    show_error=-S
    [ "${3:-}" != quiet ] || show_error=
    # A transfer slower than 1 KB/s for 30 seconds counts as stalled, so it retries or falls back.
    curl --proto "$proto" --tlsv1.2 -fsL $show_error \
        --retry 3 --connect-timeout 10 --speed-limit 1024 --speed-time 30 \
        -o "$2" "$1"
}

detect_target() {
    os=$(uname -s)
    arch=$(uname -m)

    case "$os" in
        Darwin) os=darwin ;;
        Linux) os=linux ;;
        # Git Bash, MSYS2 and Cygwin. hog on Windows keeps its settings and the install receipt under
        # LOCALAPPDATA, and PowerShell and cmd read the Windows PATH, so install.ps1 does the install.
        # WSL reports Linux and gets the Linux build.
        MINGW* | MSYS* | CYGWIN*)
            err "this is a Windows shell, so install hog with PowerShell. From this shell, run:
  powershell -NoProfile -ExecutionPolicy Bypass -Command \"irm https://releases.posthog.com/hog/install.ps1 | iex\"
or in PowerShell:
  irm https://releases.posthog.com/hog/install.ps1 | iex"
            ;;
        *) err "there is no hog build for $os." ;;
    esac

    case "$arch" in
        x86_64 | amd64) arch=x64 ;;
        arm64 | aarch64) arch=arm64 ;;
        *) err "there is no hog build for $arch processors." ;;
    esac

    # A shell under Rosetta reports x86_64 on Apple silicon. The native build is faster.
    if [ "$os" = darwin ] && [ "$arch" = x64 ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || true)" = 1 ]; then
        arch=arm64
    fi

    target="$os-$arch"

    # musl systems such as Alpine have a loader named ld-musl-<arch>.so.1, and glibc systems don't.
    if [ "$os" = linux ]; then
        for loader in /lib/ld-musl-* /usr/lib/ld-musl-*; do
            if [ -e "$loader" ]; then
                target="$target-musl"
                break
            fi
        done
    fi
}

# The manifest is one JSON object hog's release tooling writes, with a single "version" key.
manifest_version() {
    tr -d '\n' <"$1" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
}

resolve_version() {
    if [ -n "$version" ]; then
        version=${version#v}
        return
    fi

    download "$HOG_RELEASES_URL/stable/manifest.json" "$tmp/manifest.json" ||
        err "couldn't find the latest hog release at $HOG_RELEASES_URL/stable/manifest.json."

    version=$(manifest_version "$tmp/manifest.json")
    [ -n "$version" ] || err "the release manifest names no version."
}

# Tries the release bucket first and the GitHub release second, so one origin being down doesn't stop an install.
fetch_release_file() {
    download "$HOG_RELEASES_URL/v$version/$1" "$tmp/$1" quiet ||
        download "$HOG_MIRROR_URL/hog/v$version/$1" "$tmp/$1" ||
        err "couldn't download $1 for hog $version."
}

sha256_of() {
    if has sha256sum; then
        sha256sum "$1" | cut -d ' ' -f 1
    elif has shasum; then
        shasum -a 256 "$1" | cut -d ' ' -f 1
    else
        err "neither sha256sum nor shasum is installed, so the download can't be checked."
    fi
}

verify_checksum() {
    expected=$(awk -v file="$1" '$2 == file { print $1 }' "$tmp/SHA256SUMS")
    [ -n "$expected" ] || err "SHA256SUMS for hog $version has no entry for $1."

    actual=$(sha256_of "$tmp/$1")
    [ "$expected" = "$actual" ] || err "the checksum of $1 doesn't match SHA256SUMS. Nothing was installed."
}

# hog keeps its settings here too. The receipt tells a later upgrade that this script owns the binary.
config_dir() {
    if [ "$os" = darwin ]; then
        printf '%s\n' "$HOME/Library/Application Support/hog"
    else
        case "${XDG_CONFIG_HOME:-}" in
            /*) printf '%s\n' "$XDG_CONFIG_HOME/hog" ;;
            *) printf '%s\n' "$HOME/.config/hog" ;;
        esac
    fi
}

json_string() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

# Best effort: hog works without it, so a folder it can't write doesn't fail the install.
write_receipt() {
    folder=$(config_dir)
    mkdir -p "$folder" 2>/dev/null || return 0
    cat >"$folder/install.json" 2>/dev/null <<EOF || true
{
  "method": "script",
  "install_dir": "$(json_string "$install_dir")",
  "version": "$version",
  "target": "$target"
}
EOF
}

usage() {
    say "Installs hog, the PostHog command line."
    say ""
    say "Options:"
    say "  --version <version>  Install this version instead of the latest one (HOG_VERSION)"
    say "  --dir <folder>       Where to put the binary, ~/.local/bin by default (HOG_INSTALL_DIR)"
}

path_hint() {
    case ":$PATH:" in
        *":$install_dir:"*) return ;;
    esac

    say ""
    say "$install_dir isn't on your PATH yet. Add it, then open a new terminal:"
    case "$(basename "${SHELL:-sh}")" in
        zsh) say "  echo 'export PATH=\"$install_dir:\$PATH\"' >> ~/.zshrc" ;;
        bash) say "  echo 'export PATH=\"$install_dir:\$PATH\"' >> ~/.bashrc" ;;
        fish) say "  fish_add_path $install_dir" ;;
        *) say "  export PATH=\"$install_dir:\$PATH\"" ;;
    esac
}

main() {
    version="${HOG_VERSION:-}"
    install_dir="${HOG_INSTALL_DIR:-${HOME:?HOME must be set}/.local/bin}"

    while [ $# -gt 0 ]; do
        case "$1" in
            --version) version="${2:?--version needs a value}"; shift 2 ;;
            --version=*) version="${1#*=}"; shift ;;
            --dir) install_dir="${2:?--dir needs a value}"; shift 2 ;;
            --dir=*) install_dir="${1#*=}"; shift ;;
            -h | --help) usage; exit 0 ;;
            *) err "unknown option $1." ;;
        esac
    done

    has curl || err "curl is required to download hog."
    has tar || err "tar is required to unpack hog."

    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    trap 'exit 1' INT TERM

    detect_target
    resolve_version

    archive="hog-$target.tar.gz"
    say "Installing hog $version for $target."
    fetch_release_file SHA256SUMS
    fetch_release_file "$archive"
    verify_checksum "$archive"

    mkdir -p "$tmp/unpacked"
    tar -xzf "$tmp/$archive" -C "$tmp/unpacked"
    [ -f "$tmp/unpacked/hog" ] || err "$archive has no hog binary."

    # Staged next to the destination and run there first, so a build that can't run on this machine
    # never replaces a working hog, and the rename never leaves a half-written one.
    mkdir -p "$install_dir"
    staged="$install_dir/.hog.$$.tmp"
    cp "$tmp/unpacked/hog" "$staged"
    chmod 755 "$staged"
    if ! installed=$("$staged" --version 2>/dev/null); then
        rm -f "$staged"
        err "hog $version doesn't run on this machine, so the install left $install_dir as it was."
    fi
    mv -f "$staged" "$install_dir/hog"
    write_receipt

    say "Installed hog $installed to $install_dir/hog."

    found=$(command -v hog 2>/dev/null || true)
    if [ -n "$found" ] && [ "$found" != "$install_dir/hog" ]; then
        say ""
        say "Another hog at $found comes first on your PATH, so \`hog\` still runs that one."
    fi
    path_hint
}

main "$@"
exit
# sh never runs what follows, and reads it as a here-document, so it still parses the file.
# shellcheck disable=SC2317
: <<'#END_POWERSHELL'
#>
# PowerShell starts here: everything above is one comment to it.
if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) {
    Write-Host 'This script runs in sh. Install hog with: curl -fsSL https://releases.posthog.com/hog/install.sh | sh'
} else {
    Write-Host 'This script is for macOS and Linux. On Windows, install hog with: irm https://releases.posthog.com/hog/install.ps1 | iex'
}
#END_POWERSHELL
