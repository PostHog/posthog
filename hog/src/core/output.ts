import { styleText } from 'node:util'

import type { Mode } from './agent'
import type { HogError } from './errors'
import type { Runtime } from './runtime'

export type Style = 'bold' | 'dim' | 'red' | 'green' | 'yellow' | 'cyan'

const MAX_CELL_WIDTH = 48

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

    table(columns: readonly string[], rows: readonly unknown[][]): void {
        const cells = rows.map((row) => columns.map((_, index) => truncate(cellText(row[index]))))
        const widths = columns.map((column, index) =>
            Math.max(Bun.stringWidth(column), ...cells.map((row) => Bun.stringWidth(row[index] ?? '')))
        )
        const numeric = columns.map(
            (_, index) => rows.length > 0 && rows.every((row) => typeof row[index] === 'number' || row[index] == null)
        )
        const pad = (text: string, index: number): string => {
            const fill = ' '.repeat(Math.max(0, (widths[index] ?? 0) - Bun.stringWidth(text)))
            return numeric[index] ? fill + text : text + fill
        }

        this.line(columns.map((column, index) => this.style(pad(column, index), 'bold')).join('  '))
        this.line(this.style(widths.map((width) => '─'.repeat(width)).join('  '), 'dim'))
        cells.forEach((row, rowIndex) => {
            const text = row
                .map((cell, index) =>
                    rows[rowIndex]?.[index] == null ? this.style(pad(cell, index), 'dim') : pad(cell, index)
                )
                .join('  ')
            this.line(text.trimEnd())
        })
    }

    error(error: HogError): void {
        if (this.mode.format === 'json') {
            const payload = { error: { code: error.code, message: error.message, hint: error.hint } }
            this.runtime.writeStderr(`${JSON.stringify(payload)}\n`)
            return
        }
        this.runtime.writeStderr(`${this.style('Error:', 'red', 'bold')} ${error.message}\n`)
        if (error.hint) {
            this.runtime.writeStderr(`${this.style(error.hint, 'dim')}\n`)
        }
    }
}

// posthog-cli prints JSON through serde_json without `preserve_order`, so object keys come
// out sorted. Sorting here keeps hog's JSON the same for nested objects.
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

function cellText(value: unknown): string {
    if (value == null) {
        return 'null'
    }
    return typeof value === 'string' ? value : JSON.stringify(sortKeys(value))
}

function truncate(text: string): string {
    const flat = text.replace(/\s+/g, ' ')
    if (Bun.stringWidth(flat) <= MAX_CELL_WIDTH) {
        return flat
    }
    // Cut by code point, not UTF-16 unit, so an emoji is never split in half. Taking at most
    // MAX_CELL_WIDTH code points first keeps the loop short for long values.
    const chars = [...flat].slice(0, MAX_CELL_WIDTH)
    while (chars.length > 0 && Bun.stringWidth(chars.join('')) > MAX_CELL_WIDTH - 1) {
        chars.pop()
    }
    return `${chars.join('')}…`
}
