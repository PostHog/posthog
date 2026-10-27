import type { ExecutionContext } from './agent'
import { HogError } from './errors'
import type { Runtime } from './runtime'

const ANSI = { bold: [1, 22], dim: [2, 22], red: [31, 39], green: [32, 39], yellow: [33, 39], cyan: [36, 39] } as const

export type Style = keyof typeof ANSI

export class Printer {
    constructor(
        private readonly runtime: Runtime,
        readonly context: ExecutionContext
    ) {}

    style(text: string, ...styles: Style[]): string {
        if (!this.context.color) {
            return text
        }
        return styles.reduce((styled, name) => `\u001b[${ANSI[name][0]}m${styled}\u001b[${ANSI[name][1]}m`, text)
    }

    line(text = ''): void {
        this.runtime.writeStdout(`${text}\n`)
    }

    errorLine(text = ''): void {
        this.runtime.writeStderr(`${text}\n`)
    }

    json(value: unknown, pretty = false): void {
        this.line(pretty ? JSON.stringify(sortKeys(value), null, 2) : stableStringify(value))
    }

    error(error: HogError): void {
        if (this.context.format === 'json') {
            const payload = { error: { code: error.code, message: error.message, hint: error.hint } }
            this.errorLine(JSON.stringify(payload))
            return
        }
        this.errorLine(`${this.style('Error:', 'red', 'bold')} ${error.message}`)
        if (error.hint) {
            this.errorLine(this.style(error.hint, 'dim'))
        }
    }
}

// posthog-cli prints rows through serde_json without `preserve_order`, so object keys come
// out sorted. Sorting here keeps hog's JSON lines the same for nested objects.
function sortKeys(value: unknown): unknown {
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

export function stableStringify(value: unknown): string {
    return JSON.stringify(sortKeys(value))
}

const MAX_CELL_WIDTH = 48

function cellText(value: unknown): string {
    if (value === null || value === undefined) {
        return 'null'
    }
    if (typeof value === 'string') {
        return value
    }
    return stableStringify(value)
}

function truncate(text: string, width: number): string {
    const flat = text.replace(/\s+/g, ' ')
    return flat.length <= width ? flat : `${flat.slice(0, width - 1)}…`
}

export function renderTable(printer: Printer, columns: readonly string[], rows: readonly unknown[][]): string[] {
    const cells = rows.map((row) => columns.map((_, index) => truncate(cellText(row[index]), MAX_CELL_WIDTH)))
    const widths = columns.map((column, index) =>
        Math.max(column.length, ...cells.map((row) => row[index]?.length ?? 0))
    )
    const isNumeric = columns.map(
        (_, index) => rows.length > 0 && rows.every((row) => typeof row[index] === 'number' || row[index] === null)
    )
    const pad = (text: string, index: number): string =>
        isNumeric[index] ? text.padStart(widths[index] ?? 0) : text.padEnd(widths[index] ?? 0)

    const header = columns.map((column, index) => printer.style(pad(column, index), 'bold')).join('  ')
    const rule = printer.style(widths.map((width) => '─'.repeat(width)).join('  '), 'dim')
    const body = cells.map((row, rowIndex) =>
        row
            .map((text, index) => {
                const padded = pad(text, index)
                const isNull = rows[rowIndex]?.[index] === null || rows[rowIndex]?.[index] === undefined
                return isNull ? printer.style(padded, 'dim') : padded
            })
            .join('  ')
            .trimEnd()
    )
    return [header.trimEnd(), rule, ...body]
}
