import Table from 'cli-table3'
import { styleText } from 'node:util'

import type { Mode } from './agent'
import { type HogError, SERVER_DETAIL_HIDDEN, withServerDetail } from './errors'
import type { Runtime } from './runtime'

export type Style = 'bold' | 'dim' | 'red' | 'green' | 'yellow' | 'blue' | 'magenta' | 'cyan'

export type ColumnKind = 'string' | 'number' | 'boolean' | 'date' | 'json'

export interface TableColumn {
    name: string
    kind?: ColumnKind
}

const KIND_STYLES: Record<ColumnKind, Style[]> = {
    string: [],
    number: ['cyan'],
    boolean: ['yellow'],
    date: ['magenta'],
    json: ['blue'],
}

const MAX_CELL_WIDTH = 48
const MIN_CELL_WIDTH = 6
const CELL_PADDING = 2
// The border and padding around each cell in `│ a │ b │`: one bar per cell plus one, and a space on each side.
const tableOverhead = (count: number): number => count * (CELL_PADDING + 1) + 1
// C0 and C1 control characters, except tab and newline. Query results and API errors carry text
// from event data, and a raw escape sequence there could rewrite the terminal or the clipboard.
// oxlint-disable-next-line no-control-regex -- matching control characters is the point
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g

export function escapeControls(text: string): string {
    return text.replace(CONTROL, (char) => `\\x${char.charCodeAt(0).toString(16).padStart(2, '0')}`)
}

export interface Notes {
    warnings?: readonly string[]
    notes?: readonly string[]
}

export interface Report extends Notes {
    // One line that says whether the command worked, such as "Added 2 skills".
    result: string
    // `unchanged`: there was nothing to do. `partial`: only some of the work happened. `failed`: none of it did.
    status?: 'done' | 'unchanged' | 'partial' | 'failed'
    // What changed on disk, in PostHog or in an agent's settings, one line each.
    effects?: readonly string[]
}

const STATUS_MARKS: Record<NonNullable<Report['status']>, { mark: string; styles: Style[] }> = {
    done: { mark: '✓', styles: ['green', 'bold'] },
    unchanged: { mark: '•', styles: ['dim'] },
    partial: { mark: '!', styles: ['yellow', 'bold'] },
    failed: { mark: '✗', styles: ['red', 'bold'] },
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/

export class Output {
    constructor(
        private readonly runtime: Runtime,
        private readonly mode: Mode
    ) {}

    style(text: string, ...styles: Style[]): string {
        // hog decides about color itself, so styleText must not check the stream again.
        return this.mode.color && styles.length > 0 ? styleText(styles, text, { validateStream: false }) : text
    }

    line(text = ''): void {
        this.runtime.writeStdout(`${text}\n`)
    }

    // `first` names top-level keys to print before the sorted rest, so a reader that only sees the
    // start of a long answer, like an agent whose tool output is truncated, still sees them.
    json(value: unknown, { first = [] }: { first?: readonly string[] } = {}): void {
        const sorted = sortKeys(value)
        const ordered =
            first.length > 0 && sorted !== null && typeof sorted === 'object' && !Array.isArray(sorted)
                ? withKeysFirst(sorted as Record<string, unknown>, first)
                : sorted
        this.line(this.mode.format === 'json' ? JSON.stringify(ordered) : JSON.stringify(ordered, null, 2))
    }

    // One JSON value per line, so a caller can stream and parse the lines one at a time.
    jsonLines(values: Iterable<unknown>): void {
        for (const value of values) {
            this.line(JSON.stringify(sortKeys(value)))
        }
    }

    table(columns: readonly (string | TableColumn)[], rows: readonly unknown[][]): void {
        const named = columns.map((column) => (typeof column === 'string' ? { name: column } : column))
        const kinds = named.map((column, index) => column.kind ?? inferKind(rows.map((row) => row[index])))
        const cells = rows.map((row) => named.map((_, index) => cellText(row[index])))
        const widths = fitWidths(
            named.map((column, index) =>
                Math.min(
                    MAX_CELL_WIDTH,
                    Math.max(Bun.stringWidth(column.name), ...cells.map((row) => Bun.stringWidth(row[index] ?? '')))
                )
            ),
            this.mode.columns
        )

        const bar = this.style('│', 'dim')
        const table = new Table({
            head: named.map((column) => this.style(escapeControls(column.name), 'bold')),
            colWidths: widths.map((width) => width + CELL_PADDING),
            colAligns: kinds.map((kind) => (kind === 'number' ? 'right' : 'left')),
            style: { head: [], border: [] },
            // Empty row separators keep one line per row. The rule under the header goes back in below.
            chars: { left: bar, middle: bar, right: bar, mid: '', 'left-mid': '', 'mid-mid': '', 'right-mid': '' },
        })
        table.push(
            ...cells.map((row, rowIndex) =>
                row.map((text, index) => {
                    const value = rows[rowIndex]?.[index]
                    return value == null
                        ? this.style(text, 'dim')
                        : this.style(text, ...KIND_STYLES[kinds[index] ?? 'string'])
                })
            )
        )

        // The top and bottom borders are whole lines, so they take one style each instead of one per character.
        const [top = '', header = '', ...body] = table.toString().split('\n')
        const bottom = body.pop() ?? ''
        const rule = `├${widths.map((width) => '─'.repeat(width + CELL_PADDING)).join('┼')}┤`
        for (const line of [
            this.style(top, 'dim'),
            header,
            this.style(rule, 'dim'),
            ...body,
            this.style(bottom, 'dim'),
        ]) {
            this.line(line)
        }
    }

    // A command that changes something reads in one order: the result first, then what changed
    // because of it, then anything else. A person sees whether it worked before any detail.
    report({ result, status = 'done', effects = [], ...notes }: Report): void {
        const { mark, styles } = STATUS_MARKS[status]
        this.line(`${this.style(mark, ...styles)} ${result}`)
        for (const effect of effects) {
            this.line(`  ${effect}`)
        }
        this.notes(notes)
    }

    // Warnings, tips and next steps go after a command's result, apart from it.
    notes({ warnings = [], notes = [] }: Notes): void {
        if (warnings.length + notes.length === 0) {
            return
        }

        this.line()
        for (const warning of warnings) {
            this.line(this.style(warning, 'yellow'))
        }
        for (const note of notes) {
            this.line(note)
        }
    }

    error(error: HogError): void {
        const { message, hint } = printedFailure(error, this.mode.isCI)
        if (this.mode.format === 'json') {
            const payload = { error: { ...error.details, code: error.code, message, hint } }
            this.runtime.writeStderr(`${JSON.stringify(payload)}\n`)
            return
        }
        this.runtime.writeStderr(`${this.style('Error:', 'red', 'bold')} ${escapeControls(message)}\n`)
        if (hint) {
            this.runtime.writeStderr(`${this.style(escapeControls(hint), 'dim')}\n`)
        }
    }
}

// PostHog's reason is useful at a terminal, but it can repeat values from the request, and CI logs
// are often public. In CI the reason is left out and the hint says where to see it.
function printedFailure(error: HogError, isCI: boolean): { message: string; hint: string | undefined } {
    if (error.serverDetail === undefined) {
        return { message: error.message, hint: error.hint }
    }
    if (isCI) {
        return { message: error.message, hint: [error.hint, SERVER_DETAIL_HIDDEN].filter(Boolean).join(' ') }
    }
    return { message: withServerDetail(error.message, error.serverDetail), hint: error.hint }
}

// posthog-cli prints JSON through serde_json without `preserve_order`, so object keys come
// out sorted. Sorting here keeps hog's JSON the same for nested objects.
function sortKeys(value: unknown): unknown {
    // Integers too large for a JS number stay as their source text (see `parseLosslessJson` in core/json.ts).
    if (JSON.isRawJSON(value)) {
        return value
    }
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value !== null && typeof value === 'object') {
        return Object.fromEntries(
            Object.keys(value)
                .sort()
                .map((key) => [key, sortKeys((value as Record<string, unknown>)[key])])
        )
    }
    return value
}

function withKeysFirst(value: Record<string, unknown>, first: readonly string[]): Record<string, unknown> {
    const leading = first.filter((key) => Object.hasOwn(value, key))
    const rest = Object.keys(value).filter((key) => !leading.includes(key))
    return Object.fromEntries([...leading, ...rest].map((key) => [key, value[key]]))
}

function cellText(value: unknown): string {
    if (value == null) {
        return 'null'
    }
    const text = typeof value === 'string' ? value : JSON.stringify(sortKeys(value))
    return escapeControls(text.replace(/\s+/g, ' '))
}

function inferKind(values: readonly unknown[]): ColumnKind {
    const present = values.filter((value) => value != null)
    if (present.length === 0) {
        return 'string'
    }
    if (present.every((value) => typeof value === 'number' || typeof value === 'bigint' || JSON.isRawJSON(value))) {
        return 'number'
    }
    if (present.every((value) => typeof value === 'boolean')) {
        return 'boolean'
    }
    if (present.every((value) => typeof value === 'object')) {
        return 'json'
    }
    if (present.every((value) => typeof value === 'string' && ISO_DATE.test(value))) {
        return 'date'
    }
    return 'string'
}

function fitWidths(widths: readonly number[], terminalColumns: number | undefined): number[] {
    const fitted = [...widths]
    if (terminalColumns === undefined) {
        return fitted
    }
    const budget = terminalColumns - tableOverhead(fitted.length)
    let total = fitted.reduce((sum, width) => sum + width, 0)
    for (const floor of [MIN_CELL_WIDTH, 1]) {
        while (total > budget) {
            const widest = fitted.indexOf(Math.max(...fitted))
            if ((fitted[widest] ?? 0) <= floor) {
                break
            }
            fitted[widest] = (fitted[widest] ?? 0) - 1
            total -= 1
        }
    }
    return fitted
}
