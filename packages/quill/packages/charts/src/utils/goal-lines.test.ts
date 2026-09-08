import type { Series } from '../core/types'
import {
    buildGoalLineReferenceLines,
    computeSeriesNonZeroMax,
    mergeValueDomains,
    type GoalLineConfig,
} from './goal-lines'

const makeSeries = (data: number[], overrides: Partial<Series> = {}): Series => ({
    key: 'a',
    label: 'a',
    color: '#000',
    data,
    ...overrides,
})

describe('goal-lines', () => {
    describe('computeSeriesNonZeroMax', () => {
        it('returns the max non-zero finite value across all series', () => {
            expect(computeSeriesNonZeroMax([makeSeries([1, 2, 0, 5]), makeSeries([0, 0, 3, NaN])])).toBe(5)
        })

        it('ignores excluded series', () => {
            expect(
                computeSeriesNonZeroMax([
                    makeSeries([1, 2, 3]),
                    makeSeries([1000], { key: 'b', visibility: { excluded: true } }),
                ])
            ).toBe(3)
        })

        it.each([
            ['only zeros/NaN', [makeSeries([0, 0, NaN])]],
            ['empty input', []],
        ])('returns 0 when %s', (_, input) => {
            expect(computeSeriesNonZeroMax(input)).toBe(0)
        })
    })

    describe('buildGoalLineReferenceLines', () => {
        const series = [makeSeries([10, 20, 30])]

        it.each([
            ['null', null],
            ['undefined', undefined],
            ['empty', []],
        ] as const)('returns [] for %s input', (_, input) => {
            expect(buildGoalLineReferenceLines(input, series)).toEqual([])
        })

        it('maps each goal to a horizontal "goal" ReferenceLine, defaulting label position to end', () => {
            const result = buildGoalLineReferenceLines([{ label: 'Target', value: 50 }], series)
            expect(result).toHaveLength(1)
            expect(result[0]).toMatchObject({
                value: 50,
                orientation: 'horizontal',
                variant: 'goal',
                label: 'Target',
                labelPosition: 'end',
            })
        })

        it.each([
            ['propagates color via style.color', { color: 'var(--danger)' }, { style: { color: 'var(--danger)' } }],
            ['omits label when displayLabel is false', { displayLabel: false }, { label: undefined }],
            ['respects explicit labelPosition', { labelPosition: 'start' as const }, { labelPosition: 'start' }],
        ] as const)('%s', (_, lineOverrides, expectedProps) => {
            const lines: GoalLineConfig[] = [{ label: 'X', value: 50, ...lineOverrides }]
            expect(buildGoalLineReferenceLines(lines, series)[0]).toMatchObject(expectedProps)
        })

        it('drops lines when displayIfCrossed=false and value is below the series peak', () => {
            const lines: GoalLineConfig[] = [
                { label: 'Crossed', value: 5, displayIfCrossed: false },
                { label: 'Uncrossed', value: 100, displayIfCrossed: false },
            ]
            // seriesMax = 30
            expect(buildGoalLineReferenceLines(lines, series).map((r) => r.label)).toEqual(['Uncrossed'])
        })

        it('keeps lines when displayIfCrossed is undefined or true', () => {
            const lines: GoalLineConfig[] = [
                { label: 'Default', value: 5 },
                { label: 'Explicit', value: 5, displayIfCrossed: true },
            ]
            expect(buildGoalLineReferenceLines(lines, series)).toHaveLength(2)
        })
    })

    describe('mergeValueDomains', () => {
        // A pin beating the goal lines is settled at resolution, not here, so a pinned pair still
        // merges and keeps the `include` that resolution will discard.
        it.each([
            ['returns the defined side when the other is undefined', undefined, { include: [5] }, { include: [5] }],
            ['two include sets merge', { include: [5] }, { include: [50] }, { include: [5, 50] }],
            ['a bound and an include set both survive', { min: 40 }, { include: [500] }, { min: 40, include: [500] }],
            ['bounds merge field by field', { min: 40 }, { max: 90 }, { min: 40, max: 90 }],
            ['the left side wins a contested bound', { max: 60 }, { max: 90 }, { max: 60 }],
            [
                'a pin keeps the include for the resolver to drop',
                { min: 0, max: 10 },
                { include: [50] },
                { min: 0, max: 10, include: [50] },
            ],
        ] as const)('%s', (_, a, b, expected) => {
            expect(mergeValueDomains(a, b)).toEqual(expected)
        })
    })
})
