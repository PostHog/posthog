import Table from 'cli-table3'
import { styleText } from 'node:util'

import type { Mode } from './agent'
import type { HogError } from './errors'
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

    json(value: unknown): void {
        const sorted = sortKeys(value)
        this.line(this.mode.format === 'json' ? JSON.stringify(sorted) : JSON.stringify(sorted, null, 2))
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

    error(error: HogError): void {
        if (this.mode.format === 'json') {
            const payload = { error: { code: error.code, message: error.message, hint: error.hint } }
            this.runtime.writeStderr(`${JSON.stringify(payload)}\n`)
            return
        }
        this.runtime.writeStderr(`${this.style('Error:', 'red', 'bold')} ${escapeControls(error.message)}\n`)
        if (error.hint) {
            this.runtime.writeStderr(`${this.style(escapeControls(error.hint), 'dim')}\n`)
        }
    }
}

// posthog-cli prints JSON through serde_json without `preserve_order`, so object keys come
// out sorted. Sorting here keeps hog's JSON the same for nested objects.
function sortKeys(value: unknown): unknown {
    // Integers too large for a JS number stay as their source text (see parseLossless).
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
