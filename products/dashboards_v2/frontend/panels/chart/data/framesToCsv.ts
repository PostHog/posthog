import Papa from 'papaparse'

import type { DataFrame } from '../../../query/queryTypes'
import { timeKey } from './timeSeriesFrames'

type Field = DataFrame['fields'][number]
type Cell = unknown

// The field a frame's rows are named by: its time, or else its first text field.
function keyFieldOf(frame: DataFrame): Field | undefined {
    return frame.fields.find((field) => field.type === 'time') ?? frame.fields.find((field) => field.type === 'string')
}

function columnName(frame: DataFrame, field: Field, valueFields: number): string {
    if (!frame.name) {
        return field.name
    }
    return valueFields === 1 ? frame.name : `${frame.name} ${field.name}`
}

// Times join by the instant they name, as the chart joins them.
function rowKeys(field: Field): string[] {
    return field.values.map(field.type === 'time' ? timeKey : String)
}

// Papa writes an array or object cell as its bare text, which `escapeFormulae` does not check.
function cellOf(value: unknown): Cell {
    return value !== null && typeof value === 'object' ? JSON.stringify(value) : value
}

function hasRepeatedKeys(frame: DataFrame): boolean {
    const keyField = keyFieldOf(frame)
    const keys = keyField ? rowKeys(keyField) : []
    return new Set(keys).size !== keys.length
}

// One column per series, joined on the shared key, which is how a time series reads in a spreadsheet.
function wideRows(frames: DataFrame[]): Cell[][] {
    // Each key's row is labelled with the first value seen for it.
    const labels = new Map<string, Cell>()
    const columns: { name: string; byKey: Map<string, Cell> }[] = []
    for (const frame of frames) {
        const keyField = keyFieldOf(frame)!
        const valueFields = frame.fields.filter((field) => field !== keyField)
        const frameKeys = rowKeys(keyField)
        frameKeys.forEach((key, row) => {
            if (!labels.has(key)) {
                labels.set(key, cellOf(keyField.values[row]))
            }
        })
        for (const field of valueFields) {
            columns.push({
                name: columnName(frame, field, valueFields.length),
                byKey: new Map(frameKeys.map((key, row) => [key, cellOf(field.values[row])])),
            })
        }
    }
    const header = [keyFieldOf(frames[0])!.name, ...columns.map((column) => column.name)]
    return [
        header,
        ...[...labels].map(([key, label]) => [label, ...columns.map((column) => column.byKey.get(key) ?? '')]),
    ]
}

// One row per row of each frame, for frames that share no key to join on.
function longRows(frames: DataFrame[]): Cell[][] {
    const names = [...new Set(frames.flatMap((frame) => frame.fields.map((field) => field.name)))]
    const named = frames.some((frame) => frame.name)
    const rows = frames.flatMap((frame) => {
        const length = Math.max(0, ...frame.fields.map((field) => field.values.length))
        const byName = new Map<string, Field>()
        for (const field of frame.fields) {
            if (!byName.has(field.name)) {
                byName.set(field.name, field)
            }
        }
        const fields = names.map((name) => byName.get(name))
        return Array.from({ length }, (_, row) => {
            const cells = fields.map((field) => cellOf(field?.values[row] ?? ''))
            return named ? [frame.name ?? '', ...cells] : cells
        })
    })
    return [named ? ['series', ...names] : names, ...rows]
}

// A spreadsheet splits pasted text on every tab and line break and ignores quotes, so a value holding one would start
// a new cell that `escapeFormulae` never saw.
function flattenForPaste(rows: Cell[][]): Cell[][] {
    return rows.map((row) => row.map((cell) => (typeof cell === 'string' ? cell.replace(/[\t\r\n]+/g, ' ') : cell)))
}

/**
 * A chart's frames as CSV text: a header row, then the rows a person would expect to see in a spreadsheet. Pass `\t`
 * for text pasted into a spreadsheet, which puts each value on one cell by replacing its tabs and line breaks.
 */
export function framesToCsv(frames: DataFrame[], delimiter: ',' | '\t' = ','): string {
    const withFields = frames.filter((frame) => frame.fields.length > 0)
    const joinable = withFields.length > 0 && withFields.every((frame) => keyFieldOf(frame) && !hasRepeatedKeys(frame))
    // A cell that starts with `=` would run as a formula when the file opens in a spreadsheet. Papa's own pattern
    // needs the whole value on one line, so a value with a line break would slip past it.
    const rows = joinable ? wideRows(withFields) : longRows(withFields)
    return Papa.unparse(delimiter === '\t' ? flattenForPaste(rows) : rows, {
        delimiter,
        escapeFormulae: /^[=+\-@\t\r]/,
    })
}
