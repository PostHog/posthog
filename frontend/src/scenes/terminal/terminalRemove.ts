export const RM_SCRIPT = String.raw`#!/bin/sh
set -eu
resolve_target() {
    parent=$(readlink -f -- "$(dirname -- "$1")") || return 1
    if [ "$parent" = / ]; then parent=''; fi
    name=$(basename -- "$1")
    case "$name" in
        /|.|..) readlink -f -- "$1" ;;
        *) printf '%s/%s' "$parent" "$name" ;;
    esac
}
mounted=false
options=true
for argument in "$@"; do
    if [ "$options" = true ]; then
        case "$argument" in
            --) options=false; continue ;;
            -?*) continue ;;
        esac
    fi
    target=$(resolve_target "$argument") || {
        printf 'Could not resolve %s. Check the path before deleting it.\n' "$argument" >&2
        exit 1
    }
    case "$target" in
        /)
            printf 'Refusing to remove the filesystem root. Choose a specific file or folder.\n' >&2
            exit 1
            ;;
        /posthog)
            printf 'Refusing to remove the PostHog mount. Choose a file or folder inside /posthog/files.\n' >&2
            exit 1
            ;;
        /posthog/*) mounted=true ;;
    esac
done
if [ "$mounted" = false ]; then
    exec busybox rm "$@"
fi
arguments=$(
    options=true
    for argument in "$@"; do
        option=false
        if [ "$options" = true ]; then
            case "$argument" in
                --) options=false; option=true ;;
                -?*) option=true ;;
            esac
        fi
        if [ "$option" = false ]; then
            argument=$(resolve_target "$argument") || exit 1
        fi
        printf '%s' "$argument" | base64 | tr -d '\n'
        printf '\n'
    done | jq -Rsc '{argv: (split("\n")[:-1] | map(@base64d))}'
)
exec ph terminal-remove --json "$arguments" > /dev/null
`

export function parseRemovalArguments(argv: string[]): { paths: string[]; recursive: boolean; force: boolean } {
    const paths: string[] = []
    let recursive = false
    let force = false
    let options = true
    for (const argument of argv) {
        if (options && argument === '--') {
            options = false
        } else if (options && argument.startsWith('-') && argument !== '-') {
            if (argument === '--recursive') {
                recursive = true
            } else if (argument === '--force') {
                force = true
            } else if (/^-[rRf]+$/.test(argument)) {
                recursive ||= /[rR]/.test(argument)
                force ||= argument.includes('f')
            } else {
                throw new Error(
                    'For PostHog files, rm supports -r, -R, -f, --recursive, --force, and --. Confirmation is always required.'
                )
            }
        } else {
            paths.push(argument)
        }
    }
    if (!paths.length && !force) {
        throw new Error('Specify a file or folder to delete.')
    }
    return { paths, recursive, force }
}
