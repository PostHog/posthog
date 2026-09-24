import { MAX_TERMINAL_FILE_BYTES, TerminalFilesystem } from './terminalFilesystem'

const OPEN_SCRIPT = String.raw`#!/bin/sh
set -eu
if [ "$#" -gt 1 ]; then
    printf '%s\n' 'Use open with one file or folder path. Quote paths containing spaces.' >&2
    exit 1
fi
if [ "$#" -eq 0 ]; then
    set -- .
fi
target="$1"
case "$target" in
    /*) ;;
    *) target="$PWD/$target" ;;
esac
target=$(realpath "$target")
exec ph open "$target"
`

export const PH_SCRIPT = String.raw`#!/bin/sh
set -eu
set -o pipefail
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
trap 'exit 130' HUP INT TERM
previous=''
command=''
if [ "$#" -gt 0 ]; then command="$1"; fi
for argument in "$@"; do
    original="$argument"
    { if [ "$command" = '_complete' ]; then
        printf '%s' "$argument"
    else case "$argument" in
        @*) cat -- "$(printf '%s' "$argument" | cut -c2-)" ;;
        -)
            if [ "$previous" = '--json' ]; then
                cat
            else
                printf '%s' "$argument"
            fi
            ;;
        *) printf '%s' "$argument" ;;
    esac; fi; } | base64 | tr -d '\n'
    previous="$original"
    printf '\n'
done > "$temporary/args"
jq -Rs --arg cwd "$PWD" '{argv: (split("\n")[:-1] | map(@base64d)), cwd: $cwd}' < "$temporary/args" > "$temporary/request"
exec 9>/tmp/posthog-ph.lock
flock -x 9
cat "$temporary/request" > /posthog/.ph/request
response=$(cat /posthog/.ph/response)
flock -u 9
if printf '%s' "$response" | jq -e '.ok' >/dev/null; then
    printf '%s' "$response" | jq -r '.result'
else
    printf '%s' "$response" | jq -r '.error' >&2
    exit 1
fi
`

export const SHELL_RC = `
alias ls='ls --color=auto'
if [ -n "$BASH_VERSION" ]; then
    _ph_complete() {
        mapfile -t COMPREPLY < <(ph _complete "$COMP_CWORD" "$2" "$3" "\${COMP_WORDS[1]}" 2>/dev/null)
        if [ "\${#COMPREPLY[@]}" -eq 1 ] && [ -z "\${COMPREPLY[0]}" ]; then COMPREPLY=(); fi
    }
    complete -o bashdefault -o default -F _ph_complete ph
fi
`

export const RUN_HELP = `Usage: run [format] <file[.sql]>

Run a SQL file in the current PostHog project.
If the file is missing, run also looks for <file>.sql.

Formats (choose one, before or after the filename):
  --markdown       Markdown table with headers and rows (default)
  --json           Full query result as JSON, including metadata
  --csv            Comma-separated headers and rows
  --tsv            Tab-separated headers and rows
  --help, -h       Show this help

Markdown, CSV, and TSV contain only the returned table. Use --json
to check hasMore for additional rows. CSV and TSV quote fields containing
delimiters, quotes, or newlines; null values are empty fields.

Examples:
  run report.sql
  run report > results.md
  run --json report.sql > /tmp/results.json
  run report.sql --csv > /tmp/results.csv

Use /tmp for exports.
Query errors go to stderr and exit nonzero.
`

const RUN_SCRIPT = String.raw`#!/bin/sh
set -eu
usage() {
    cat <<'HELP'
${RUN_HELP}
HELP
}
format=''
file=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --markdown|--json|--csv|--tsv)
            [ -z "$format" ] || { echo 'Choose one output format. Run run --help for formats.' >&2; exit 1; }
            format="$1"
            ;;
        --)
            shift
            [ "$#" -eq 1 ] && [ -z "$file" ] || { usage >&2; exit 1; }
            file="$1"
            break
            ;;
        -*) echo "Unknown option: $1. Run run --help for options." >&2; exit 1 ;;
        *) [ -z "$file" ] || { usage >&2; exit 1; }; file="$1" ;;
    esac
    shift
done
[ -n "$file" ] || { usage >&2; exit 1; }
if [ ! -e "$file" ] && [ -f "$file.sql" ]; then file="$file.sql"; fi
case "$file" in
    *.sql) ;;
    *.md) echo 'Running Markdown notebooks is not supported yet. Use run <file.sql>.' >&2; exit 1 ;;
    *) echo 'Only .sql files can be run. Use run <file.sql>.' >&2; exit 1 ;;
esac
[ -f "$file" ] || { echo "SQL file not found: $file" >&2; exit 1; }
target=$(readlink -f -- "$file")
[ -n "$format" ] || format='--markdown'
exec ph run "$target" "@$target" "$format"
`

export class TerminalCommands {
    constructor(filesystem: TerminalFilesystem, execute: (argv: string[], cwd: string) => Promise<unknown>) {
        const encoder = new TextEncoder()
        const decoder = new TextDecoder('utf-8', { fatal: true })
        const envelope = (value: object): Uint8Array => encoder.encode(JSON.stringify(value))
        let response = envelope({ ok: false, error: 'Run a ph command first.' })
        const directory = filesystem.directory('.ph', filesystem.root)
        const responseNode = filesystem.file('response', directory, async () => ({ bytes: response }))
        filesystem.file(
            'request',
            directory,
            async () => ({
                bytes: new Uint8Array(),
                save: async (bytes) => {
                    try {
                        const request = JSON.parse(decoder.decode(bytes))
                        if (
                            !request ||
                            !Array.isArray(request.argv) ||
                            request.argv.length > 1000 ||
                            !request.argv.every((value: unknown) => typeof value === 'string') ||
                            typeof request.cwd !== 'string'
                        ) {
                            throw new Error('Invalid command request. Run ph help for usage.')
                        }
                        const result = await execute(request.argv, request.cwd)
                        const encoded = envelope({ ok: true, result: result ?? null })
                        if (encoded.length > MAX_TERMINAL_FILE_BYTES) {
                            throw new Error('The result exceeds 4 MiB. Reduce the limit or narrow the query.')
                        }
                        response = encoded
                    } catch (error) {
                        // A failed tool can put its whole payload in the message, and the guest reads
                        // this file into a shell variable inside the virtual machine.
                        const encoded = envelope({
                            ok: false,
                            error: error instanceof Error ? error.message : 'The command failed. Try ph help.',
                        })
                        response =
                            encoded.length > MAX_TERMINAL_FILE_BYTES
                                ? envelope({
                                      ok: false,
                                      error: 'The command failed, and its error exceeds 4 MiB. Check the tool that returned it.',
                                  })
                                : encoded
                    }
                    responseNode.size = response.length
                },
            }),
            true
        )
        const bin = filesystem.directory('bin', filesystem.root)
        filesystem.text('ph', bin, PH_SCRIPT)
        filesystem.text('run', bin, RUN_SCRIPT)
        filesystem.text('shellrc', bin, SHELL_RC)
        filesystem.text('open', bin, OPEN_SCRIPT)
    }
}
