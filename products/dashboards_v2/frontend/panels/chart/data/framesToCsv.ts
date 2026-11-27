import Papa from 'papaparse'

import type { DataFrame } from '../../../query/queryTypes'

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

function hasRepeatedKeys(frame: DataFrame): boolean {
    const keys = keyFieldOf(frame)?.values.map(String) ?? []
    return new Set(keys).size !== keys.length
}

// One column per series, joined on the shared key, which is how a time series reads in a spreadsheet.
function wideRows(frames: DataFrame[]): Cell[][] {
    const keys: string[] = []
    const seen = new Set<string>()
    const columns: { name: string; byKey: Map<string, Cell> }[] = []
    for (const frame of frames) {
        const keyField = keyFieldOf(frame)!
        const valueFields = frame.fields.filter((field) => field !== keyField)
        const frameKeys = keyField.values.map(String)
        for (const key of frameKeys) {
            if (!seen.has(key)) {
                seen.add(key)
                keys.push(key)
            }
        }
        for (const field of valueFields) {
            columns.push({
                name: columnName(frame, field, valueFields.length),
                byKey: new Map(frameKeys.map((key, row) => [key, field.values[row]])),
            })
        }
    }
    const header = [keyFieldOf(frames[0])!.name, ...columns.map((column) => column.name)]
    return [header, ...keys.map((key) => [key, ...columns.map((column) => column.byKey.get(key) ?? '')])]
}

// One row per row of each frame, for frames that share no key to join on.
function longRows(frames: DataFrame[]): Cell[][] {
    const names = [...new Set(frames.flatMap((frame) => frame.fields.map((field) => field.name)))]
    const named = frames.some((frame) => frame.name)
    const rows = frames.flatMap((frame) => {
        const length = Math.max(0, ...frame.fields.map((field) => field.values.length))
        return Array.from({ length }, (_, row) => {
            const cells = names.map((name) => frame.fields.find((field) => field.name === name)?.values[row] ?? '')
            return named ? [frame.name ?? '', ...cells] : cells
        })
    })
    return [named ? ['series', ...names] : names, ...rows]
}

/** A chart's frames as CSV text: a header row, then the rows a person would expect to see in a spreadsheet. */
export function framesToCsv(frames: DataFrame[]): string {
    const withFields = frames.filter((frame) => frame.fields.length > 0)
    const joinable = withFields.length > 0 && withFields.every((frame) => keyFieldOf(frame) && !hasRepeatedKeys(frame))
    // A cell that starts with `=` would run as a formula when the file opens in a spreadsheet.
    return Papa.unparse(joinable ? wideRows(withFields) : longRows(withFields), { escapeFormulae: true })
}
