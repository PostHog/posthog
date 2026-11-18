import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

export const HOGQL_HELP = `Usage: hogql [options] ["SQL"]
       echo "SQL" | hogql [options]
       hogql [options]

Run SQL in the current PostHog project. Without SQL or piped input, start
an interactive prompt. Enter one query per line; no semicolon is required.
Use exit, quit, \\q, or Ctrl+D to leave. Query errors keep the prompt open.

Output (choose one):
  --markdown          Markdown table (default)
  --json              Full query response, including metadata and hasMore
  --csv               Comma-separated headers and rows
  --tsv               Tab-separated headers and rows

Query options:
  --connection-id ID  Query an external connection instead of PostHog data
  --raw               Send SQL to that connection without HogQL translation
  --name NAME         Set the query name
  --values JSON       Placeholder values, for example '{"value":42}'
  --filters JSON      Filters used by the {filters} placeholder
  --variables JSON    Saved query variables
  --modifiers JSON    HogQL query modifiers
  --field NAME=JSON   Add a top-level query field; repeat for multiple fields
  --help, -h          Show this help
  --                 Treat the next argument as SQL, even if it starts with -

JSON options must be objects. --field values must be valid JSON; quote strings.
Fields use API names, such as sendRawQuery. kind and query cannot be overridden.
Options apply to every query in an interactive session. Use LIMIT and OFFSET
in SQL to page through results. --json includes hasMore when more rows exist.
CSV and TSV quote special characters; null values become empty fields.
Errors go to stderr and exit nonzero outside interactive mode.
Warnings go to stderr in every output format. Ctrl+C cancels the current query.

Examples:
  hogql "select 1"
  echo "select 1" | hogql --json
  hogql --csv "select event, count() from events group by event" > /tmp/events.csv
  hogql --values '{"value":42}' "select {value}"
  hogql --connection-id CONNECTION_ID "select * from orders limit 10"
  hogql --modifiers '{"debug":true}' --json "select 1"
  hogql --connection-id CONNECTION_ID --raw
`

export const HOGQL_FLAGS = [
    '--markdown',
    '--json',
    '--csv',
    '--tsv',
    '--connection-id',
    '--raw',
    '--name',
    '--values',
    '--filters',
    '--variables',
    '--modifiers',
    '--field',
    '--help',
]

export const HOGQL_SCRIPT = String.raw`#!/usr/bin/bash
set -euo pipefail
usage() {
    cat <<'HELP'
${HOGQL_HELP}
HELP
}
options=()
query=''
has_query=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --markdown|--json|--csv|--tsv|--raw) options+=("$1") ;;
        --connection-id|--name|--values|--filters|--variables|--modifiers|--field)
            [ "$#" -ge 2 ] || { echo "Missing value for $1. Run hogql --help." >&2; exit 1; }
            options+=("$1" "$2")
            shift
            ;;
        --)
            shift
            [ "$#" -eq 1 ] && ! "$has_query" || { usage >&2; exit 1; }
            query="$1"
            has_query=true
            break
            ;;
        -*) echo "Unknown option: $1. Run hogql --help." >&2; exit 1 ;;
        *)
            ! "$has_query" || { echo 'Quote the SQL as one argument. Run hogql --help.' >&2; exit 1; }
            query="$1"
            has_query=true
            ;;
    esac
    shift
done
execute_query() {
    printf '%s' "$1" |
        jq -cRs --args '{query: ., argv: $ARGS.positional}' -- "${'$'}{options[@]}" |
        ph hogql --json -
}
if "$has_query"; then
    execute_query "$query"
elif [ ! -t 0 ]; then
    execute_query "$(cat)"
else
    printf '%s\n' 'Enter one SQL query per line. Use exit or Ctrl+D to leave.' >&2
    while IFS= read -e -r -p 'hogql> ' query; do
        case "$query" in exit|quit|'\q') break ;; esac
        [ -n "${'$'}{query//[[:space:]]/}" ] || continue
        history -s "$query"
        execute_query "$query" || true
    done
fi
`

function jsonField(text: string, option: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        throw new Error(`Invalid JSON for ${option}. Run hogql --help for examples.`)
    }
}

type HogqlFormat = 'markdown' | 'json' | 'csv' | 'tsv'

export function terminalHogqlQuery(text: string, argv: string[]): { query: HogQLQuery; format: HogqlFormat } {
    if (!text.trim()) {
        throw new Error('The query is empty. Pass SQL as an argument or pipe it to hogql.')
    }
    let format: HogqlFormat | undefined
    const fields: Record<string, unknown> = {}
    for (let index = 0; index < argv.length; index++) {
        const option = argv[index]
        if (['--markdown', '--json', '--csv', '--tsv'].includes(option)) {
            if (format) {
                throw new Error('Choose one output format. Run hogql --help for formats.')
            }
            format = option.slice(2) as HogqlFormat
            continue
        }
        if (option === '--raw') {
            fields.sendRawQuery = true
            continue
        }
        if (!HOGQL_FLAGS.includes(option) || option === '--help') {
            throw new Error(`Unknown option: ${option}. Run hogql --help.`)
        }
        const value = argv[++index]
        if (value === undefined) {
            throw new Error(`Missing value for ${option}. Run hogql --help.`)
        }
        if (option === '--connection-id' || option === '--name') {
            if (!value.trim()) {
                throw new Error(`Provide a nonempty value for ${option}.`)
            }
            fields[option === '--connection-id' ? 'connectionId' : 'name'] = value
        } else if (option === '--field') {
            const separator = value.indexOf('=')
            const name = value.slice(0, separator)
            if (separator <= 0 || ['kind', 'query', '__proto__', 'constructor', 'prototype'].includes(name)) {
                throw new Error('Use --field name=JSON for a query field other than kind or query.')
            }
            fields[name] = jsonField(value.slice(separator + 1), '--field')
        } else {
            const parsed = jsonField(value, option)
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
                throw new Error(`${option} requires a JSON object. Run hogql --help for examples.`)
            }
            fields[option.slice(2)] = parsed
        }
    }
    if (fields.sendRawQuery && !fields.connectionId) {
        throw new Error('Raw SQL requires --connection-id. Run hogql --help.')
    }
    return {
        query: {
            tags: { productKey: 'sql_editor', scene: 'Terminal' },
            ...fields,
            kind: NodeKind.HogQLQuery,
            query: text,
        },
        format: format ?? 'markdown',
    }
}
