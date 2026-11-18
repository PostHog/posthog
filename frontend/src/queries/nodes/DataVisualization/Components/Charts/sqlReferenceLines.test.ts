import type { Series } from '@posthog/quill-charts'

import { resolveSQLReferenceLines } from './sqlReferenceLines'

const series: Series[] = [
    { key: 'basic', label: 'Basic', data: [0, 10, NaN, 20] },
    { key: 'plus', label: 'Plus', data: [30, 50] },
    { key: 'right', label: 'Secondary axis', data: [1000], yAxisId: 'right' },
    { key: 'excluded', label: 'Excluded', data: [2000], visibility: { excluded: true } },
]

describe('resolveSQLReferenceLines', () => {
    it.each([
        ['mean', 22],
        ['median', 20],
        ['min', 0],
        ['max', 50],
    ] as const)('calculates %s from finite primary-axis marks, including zero', (calculation, expected) => {
        expect(resolveSQLReferenceLines([{ label: 'Reference', value: 999, calculation }], series)).toEqual([
            expect.objectContaining({ label: 'Reference', value: expected }),
        ])
    })

    it('calculates each group separately and leaves saved settings unchanged as results change', () => {
        const line = { label: 'Average', value: 999, calculation: 'mean' as const, scope: 'series' as const }
        expect(resolveSQLReferenceLines([line], series)).toEqual([
            { ...line, label: 'Average · Basic', value: 10 },
            { ...line, label: 'Average · Plus', value: 40 },
        ])
        expect(resolveSQLReferenceLines([line], [{ key: 'basic', label: 'Basic', data: [12, 18] }])).toEqual([
            { ...line, label: 'Average · Basic', value: 15 },
        ])
        expect(line.value).toBe(999)
    })

    it('keeps constant lines while omitting calculated lines without finite values', () => {
        const fixed = { label: 'Target', value: 50 }
        const mean = { label: 'Average', value: 0, calculation: 'mean' as const }
        expect(resolveSQLReferenceLines([fixed, mean], [])).toEqual([fixed])
        expect(resolveSQLReferenceLines([fixed, mean], series, true)).toEqual([fixed])
        expect(resolveSQLReferenceLines([mean], [{ key: 'empty', label: 'Empty', data: [NaN, Infinity] }])).toEqual([])
    })
})
