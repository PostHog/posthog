import {
    getDotMatrixCellCount,
    getDotMatrixCountBin,
    normalizeDotMatrixCountScale,
    normalizeDotMatrixData,
    normalizeDotMatrixSizeThresholds,
    toggleDotMatrixSeries,
} from './dotMatrixData'
import type { DotMatrixCell, DotMatrixCountBin } from './types'

interface Observation extends Record<string, unknown> {
    row: string
    column: string
    series: string
    value: number
    people?: string[]
}

const fields = { row: 'row', column: 'column', series: 'series', value: 'value' } as const

function normalize(data: Observation[]): ReturnType<typeof normalizeDotMatrixData<Observation>> {
    return normalizeDotMatrixData({ data, fields })
}

const scale: DotMatrixCountBin[] = [
    { min: 10, color: 'high', ink: 'dark' },
    { min: 1, color: 'low' },
    { min: 5, color: 'medium' },
]

describe('dotMatrixData', () => {
    it('keeps explicit axis metadata and fills missing intersections while appending new keys', () => {
        const data: Observation[] = [
            { row: 'new', column: 'later', series: 'unknown', value: 5 },
            { row: 'first', column: 'earlier', series: 'known', value: 1 },
        ]
        const matrix = normalizeDotMatrixData({
            data,
            fields,
            rows: [{ key: 'first', label: 'First', group: 'group' }, { key: 'empty' }],
            columns: [{ key: 'earlier', label: 'Earlier', partial: true }],
            series: [{ key: 'known', label: 'Known', color: 'blue' }],
        })

        expect(matrix.rows).toEqual([
            { key: 'first', label: 'First', group: 'group' },
            { key: 'empty' },
            { key: 'new' },
        ])
        expect(matrix.columns).toEqual([{ key: 'earlier', label: 'Earlier', partial: true }, { key: 'later' }])
        expect(matrix.series).toEqual([{ key: 'known', label: 'Known', color: 'blue' }, { key: 'unknown' }])
        expect(matrix.getCell('empty', 'later')).toEqual({ rowKey: 'empty', columnKey: 'later', values: {}, data: [] })
        expect(matrix.cells.get('new')?.size).toBe(2)
        expect(matrix.getCell('new', 'later').data[0]).toBe(data[0])
    })

    it.each([false, true])('accepts function fields and numeric keys (empty series field: %p)', (emptySeriesField) => {
        const data = [{ account: 17, bucket: 0, kind: 'job', amount: '5', '': 'job' }]
        const matrix = normalizeDotMatrixData({
            data,
            fields: {
                row: (datum) => datum.account,
                column: (datum) => datum.bucket,
                series: emptySeriesField ? '' : (datum: (typeof data)[number]) => datum.kind,
                value: (datum) => datum.amount,
            },
        })

        expect(matrix.rows).toEqual([{ key: '17' }])
        expect(matrix.columns).toEqual([{ key: '0' }])
        expect(matrix.getCell('17', '0').values).toEqual({ job: 5 })
        expect(data).toEqual([{ account: 17, bucket: 0, kind: 'job', amount: '5', '': 'job' }])
    })

    it('retains the last valid duplicate value and all source records for caller aggregation', () => {
        const data: Observation[] = [
            { row: 'r', column: 'c', series: 's', value: 3, people: ['one', 'two'] },
            { row: 'r', column: 'c', series: 's', value: 5, people: ['two', 'three'] },
            { row: 'r', column: 'c', series: 's', value: Number.NaN },
        ]
        const cell = normalize(data).getCell('r', 'c')

        expect(cell.values).toEqual({ s: 5 })
        expect(cell.data).toEqual(data.slice(0, 2))
    })

    it('keeps prototype names and delimiter-like coordinate keys distinct', () => {
        const matrix = normalize([
            { row: '__proto__', column: 'constructor', series: '__proto__', value: 3 },
            { row: 'a|b', column: 'c', series: 'constructor', value: 5 },
            { row: 'a', column: 'b|c', series: 'toString', value: 10 },
        ])

        expect(matrix.getCell('__proto__', 'constructor').values.__proto__).toBe(3)
        expect(matrix.getCell('a|b', 'c').values.constructor).toBe(5)
        expect(matrix.getCell('a', 'b|c').values.toString).toBe(10)
        expect(matrix.getCell('missing', 'missing').values).toEqual({})
    })

    it.each([Number.NaN, Infinity, -Infinity, null, undefined, '', ' ', true, {}])(
        'ignores an observation with an invalid numeric value %p',
        (value) => {
            const matrix = normalizeDotMatrixData({
                data: [{ row: 'r', column: 'c', series: 's', value }],
                fields,
            })
            expect(matrix.rows).toEqual([])
            expect(matrix.columns).toEqual([])
            expect(matrix.series).toEqual([])
        }
    )

    it.each(['row', 'column', 'series'] as const)('ignores observations with a missing %s key', (key) => {
        const data = { row: 'r', column: 'c', series: 's', value: 1, [key]: null }
        expect(normalizeDotMatrixData({ data: [data], fields }).rows).toEqual([])
    })

    it('deduplicates explicit axes and retains requested empty axes without observations', () => {
        const matrix = normalizeDotMatrixData<Observation>({
            data: [],
            fields,
            rows: [
                { key: 'r', label: 'First' },
                { key: 'r', label: 'Duplicate' },
            ],
            columns: [{ key: 'c' }],
            series: [{ key: 's' }, { key: 's' }],
        })

        expect(matrix.rows).toEqual([{ key: 'r', label: 'First' }])
        expect(matrix.series).toEqual([{ key: 's' }])
        expect(matrix.getCell('r', 'c')).toEqual({ rowKey: 'r', columnKey: 'c', values: {}, data: [] })
    })

    it('reads a raw count when no series field is mapped', () => {
        const matrix = normalizeDotMatrixData({
            data: [{ row: 'r', column: 'c', value: 17 }],
            fields: { row: 'row', column: 'column', value: 'value' },
        })

        expect(matrix.series).toEqual([])
        expect(getDotMatrixCellCount(matrix.getCell('r', 'c'), { countOf: 'value' })).toBe(17)
        expect(getDotMatrixCellCount(matrix.getCell('r', 'missing'), { countOf: 'value' })).toBe(0)
    })

    it('counts active series and requires caller aggregation for selected values', () => {
        const cell = normalize([
            { row: 'r', column: 'c', series: 'logs', value: 2, people: ['one', 'two'] },
            { row: 'r', column: 'c', series: 'traces', value: 2, people: ['two', 'three'] },
            { row: 'r', column: 'c', series: 'errors', value: 0 },
        ]).getCell('r', 'c')
        const selectedSeries = ['logs', 'traces']

        expect(getDotMatrixCellCount(cell)).toBe(2)
        expect(getDotMatrixCellCount(cell, { selectedSeries })).toBeNull()
        expect(
            getDotMatrixCellCount(cell, {
                selectedSeries,
                aggregateSelection: (selectedCell, selected) =>
                    new Set(
                        selectedCell.data
                            .filter((datum) => selected.includes(datum.series))
                            .flatMap((datum) => datum.people ?? [])
                    ).size,
            })
        ).toBe(3)
    })

    it.each([Infinity, Number.NaN])('hides invalid caller aggregation results %p', (value) => {
        const cell: DotMatrixCell<Observation> = { rowKey: 'r', columnKey: 'c', values: { s: 1 }, data: [] }
        expect(getDotMatrixCellCount(cell, { selectedSeries: ['s'], aggregateSelection: () => value })).toBeNull()
    })

    it.each([
        { selected: ['a'], key: 'b', shift: false, expected: ['b'] },
        { selected: ['a'], key: 'a', shift: false, expected: ['a'] },
        { selected: ['a'], key: 'b', shift: true, expected: ['a', 'b'] },
        { selected: ['a', 'b'], key: 'a', shift: true, expected: ['b'] },
        { selected: ['a'], key: 'a', shift: true, expected: [] },
    ])('applies legend selection $selected + $key (shift=$shift)', ({ selected, key, shift, expected }) => {
        const original = [...selected]
        expect(toggleDotMatrixSeries(selected, key, shift)).toEqual(expected)
        expect(selected).toEqual(original)
    })

    it.each([
        { thresholds: undefined, expected: [1, 5, 10] },
        { thresholds: [], expected: [] },
        { thresholds: [1], expected: [1] },
        { thresholds: [10, 1, 5, 5, 20, Number.NaN, Infinity, 0, -1], expected: [1, 5, 10] },
    ])('normalizes configured size thresholds $thresholds without adding levels', ({ thresholds, expected }) => {
        const original = thresholds && [...thresholds]
        expect(normalizeDotMatrixSizeThresholds(thresholds)).toEqual(expected)
        expect(thresholds).toEqual(original)
    })

    it('orders valid count bins and keeps the first duplicate without mutating caller data', () => {
        const bins = [...scale, { min: Number.NaN, color: 'invalid' }, { min: 5, color: 'duplicate' }]
        const original = [...bins]
        expect(normalizeDotMatrixCountScale(bins)).toEqual([scale[1], scale[2], scale[0]])
        expect(bins).toEqual(original)
    })

    it.each([
        [0, undefined],
        [1, 'low'],
        [4, 'low'],
        [5, 'medium'],
        [9, 'medium'],
        [10, 'high'],
        [50, 'high'],
        [-1, undefined],
        [Number.NaN, undefined],
        [Infinity, undefined],
    ])('selects the count bin at value %p', (value, expected) => {
        expect(getDotMatrixCountBin(value as number, scale)?.color).toBe(expected)
    })

    it('lets the caller count a cell when no series is selected', () => {
        const cell = { rowKey: 'r', columnKey: 'c', values: { a: 2, b: 1 }, data: [] }
        expect(getDotMatrixCellCount(cell, { countOf: () => 2 })).toBe(2)
        expect(getDotMatrixCellCount(cell, { countOf: () => Infinity })).toBeNull()
    })
})
