import type { CommandUnknownOpts } from '@commander-js/extra-typings'

import { PostHogApi } from '../api'
import { resolveCredentials } from '../credentials'
import { HogError } from '../errors'
import { renderTable, type Printer } from '../output'
import type { CommandContext } from '../program'

interface QueryErrorBody {
    type?: string
    code?: string
    detail?: string
}

interface QueryResponse {
    columns?: string[] | null
    results?: unknown[][] | null
    hasMore?: boolean | null
}

interface MetadataNotice {
    message: string
    start?: number
    end?: number
}

interface MetadataResponse {
    isValid?: boolean | null
    errors?: MetadataNotice[] | null
    warnings?: MetadataNotice[] | null
    notices?: MetadataNotice[] | null
}

async function queryText(argument: string, context: CommandContext): Promise<string> {
    const text = argument === '-' ? await context.runtime.readStdin() : argument
    if (!text.trim()) {
        throw new HogError('empty_query', 'The query is empty.', 'Pass the query as an argument, or pipe it in with -.')
    }
    return text
}

async function apiFor(context: CommandContext): Promise<PostHogApi> {
    const credentials = await resolveCredentials(context.runtime, {
        host: context.globals.host,
        dotenvFile: context.globals.dotenvFile,
    })
    return new PostHogApi(credentials, context.runtime.fetch, context.userAgent)
}

function queryFailure(status: number, body: unknown): HogError {
    const error = (body ?? {}) as QueryErrorBody
    const code = error.code ?? `http_${status}`
    const detail = error.detail ?? `PostHog answered with HTTP ${status}.`
    const hint =
        status === 401 || status === 403
            ? 'Check that the personal API key is valid and has the query:read scope.'
            : error.type === 'validation_error'
              ? 'Run `hog query check` on the query to see where it fails.'
              : undefined
    return new HogError(code, detail, hint)
}

function printRows(printer: Printer, response: QueryResponse): void {
    const columns = response.columns ?? []
    const rows = response.results ?? []
    if (printer.context.format === 'json') {
        for (const row of rows) {
            printer.json(row)
        }
        return
    }
    for (const line of renderTable(printer, columns, rows)) {
        printer.line(line)
    }
    const count = `${rows.length} ${rows.length === 1 ? 'row' : 'rows'}`
    printer.line(printer.style(response.hasMore ? `${count}, more available` : count, 'dim'))
}

// Converts a character offset into a 1-based line and column, and returns that line's text.
function locate(source: string, offset: number): { line: number; column: number; text: string } {
    const before = source.slice(0, offset).split('\n')
    const line = before.length
    const column = (before.at(-1)?.length ?? 0) + 1
    return { line, column, text: source.split('\n')[line - 1] ?? '' }
}

function printCheck(printer: Printer, source: string, response: MetadataResponse): void {
    const groups = [
        { label: 'error', style: 'red' as const, items: response.errors ?? [] },
        { label: 'warning', style: 'yellow' as const, items: response.warnings ?? [] },
        { label: 'notice', style: 'cyan' as const, items: response.notices ?? [] },
    ]
    for (const group of groups) {
        for (const item of group.items) {
            printer.line(`${printer.style(group.label, group.style, 'bold')}: ${item.message}`)
            if (item.start === undefined) {
                continue
            }
            const { line, column, text } = locate(source, item.start)
            const width = Math.max(1, Math.min((item.end ?? item.start + 1) - item.start, text.length - column + 1))
            const gutter = `${line} | `
            printer.line(printer.style(`  --> line ${line}, column ${column}`, 'dim'))
            printer.line(`  ${printer.style(gutter, 'dim')}${text}`)
            printer.line(`  ${' '.repeat(gutter.length + column - 1)}${printer.style('^'.repeat(width), group.style)}`)
        }
    }
    const [errors, warnings, notices] = groups.map((group) => group.items.length)
    const summary = `${errors} ${errors === 1 ? 'error' : 'errors'}, ${warnings} ${warnings === 1 ? 'warning' : 'warnings'}, ${notices} ${notices === 1 ? 'notice' : 'notices'}`
    printer.line(errors === 0 ? printer.style(`Query is valid (${summary})`, 'green') : printer.style(summary, 'red'))
}

export function registerQueryCommand(
    program: CommandUnknownOpts,
    contextFor: (command: CommandUnknownOpts) => CommandContext
): void {
    const query = program.command('query').description('Run and check HogQL queries against your project')

    query
        .command('run')
        .description('Run a HogQL query and print the results')
        .argument('<query>', 'The HogQL query to run, or - to read it from stdin')
        .option('--debug', 'Print the full JSON response instead of just the results')
        .addHelpText(
            'after',
            '\nPrints a table in a terminal, and one JSON array per row for agents and pipes.\n\nExample:\n  hog query run "select event, count() from events group by event"'
        )
        .action(async (argument, options, command) => {
            const context = contextFor(command)
            const text = await queryText(argument, context)
            const api = await apiFor(context)
            const response = await api.postEnvironment('query', {
                query: { kind: 'HogQLQuery', query: text },
                refresh: 'blocking',
            })
            if (!response.ok) {
                throw queryFailure(response.status, response.body)
            }
            if (options.debug) {
                context.printer.json(response.body, true)
                return
            }
            printRows(context.printer, response.body as QueryResponse)
        })

    query
        .command('check')
        .description('Check the syntax and types of a HogQL query without running it')
        .argument('<query>', 'The HogQL query to check, or - to read it from stdin')
        .option('--raw', 'Print the raw JSON response from PostHog')
        .addHelpText('after', '\nExits with code 1 when the query has errors, so scripts and agents can branch on it.')
        .action(async (argument, options, command) => {
            const context = contextFor(command)
            const text = await queryText(argument, context)
            const api = await apiFor(context)
            const response = await api.postEnvironment('query', {
                query: { kind: 'HogQLMetadata', language: 'hogQL', query: text },
            })
            const body = (response.body ?? {}) as MetadataResponse
            if (!response.ok && body.errors === undefined) {
                throw queryFailure(response.status, response.body)
            }
            if (options.raw || context.printer.context.format === 'json') {
                context.printer.json(response.body, options.raw === true)
            } else {
                printCheck(context.printer, text, body)
            }
            if ((body.errors ?? []).length > 0) {
                context.setExitCode(1)
            }
        })
}
