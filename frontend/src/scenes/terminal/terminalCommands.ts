import { MAX_TERMINAL_FILE_BYTES, TerminalFilesystem } from './terminalFilesystem'

export const PH_SCRIPT = String.raw`#!/bin/sh
set -eu
args='[]'
previous=''
for argument in "$@"; do
    original="$argument"
    case "$argument" in
        @*) argument=$(cat "$(printf '%s' "$argument" | cut -c2-)") ;;
        -) if [ "$previous" = '--json' ]; then argument=$(cat); fi ;;
    esac
    args=$(jq -nc --argjson args "$args" --arg value "$argument" '$args + [$value]')
    previous="$original"
done
request=$(jq -nc --argjson argv "$args" --arg cwd "$PWD" '{argv: $argv, cwd: $cwd}')
exec 9>/tmp/posthog-ph.lock
flock -x 9
printf '%s' "$request" > /posthog/.ph/request
response=$(cat /posthog/.ph/response)
flock -u 9
if printf '%s' "$response" | jq -e '.ok' >/dev/null; then
    printf '%s' "$response" | jq -r '.result'
else
    printf '%s' "$response" | jq -r '.error' >&2
    exit 1
fi
`

export class TerminalCommands {
    constructor(filesystem: TerminalFilesystem, execute: (argv: string[], cwd: string) => Promise<unknown>) {
        const encoder = new TextEncoder()
        const decoder = new TextDecoder('utf-8', { fatal: true })
        let response = encoder.encode(JSON.stringify({ ok: false, error: 'Run a ph command first.' }))
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
                        const encoded = encoder.encode(JSON.stringify({ ok: true, result: result ?? null }))
                        if (encoded.length > MAX_TERMINAL_FILE_BYTES) {
                            throw new Error('The result exceeds 4 MiB. Reduce the limit or narrow the query.')
                        }
                        response = encoded
                    } catch (error) {
                        response = encoder.encode(
                            JSON.stringify({
                                ok: false,
                                error: error instanceof Error ? error.message : 'The command failed. Try ph help.',
                            })
                        )
                    }
                    responseNode.size = response.length
                },
            }),
            true
        )
        filesystem.text('ph', filesystem.directory('bin', filesystem.root), PH_SCRIPT)
    }
}
