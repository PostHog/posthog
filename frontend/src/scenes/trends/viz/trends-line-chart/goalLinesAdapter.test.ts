import { computeSeriesNonZeroMax } from 'lib/hog-charts'
import type { Series } from 'lib/hog-charts'

import type { GoalLine as SchemaGoalLine } from '~/queries/schema/schema-general'

import { alertThresholdsToReferenceLines, goalLinesToReferenceLines } from './goalLinesAdapter'

const makeSeries = (data: number[], overrides: Partial<Series> = {}): Series => ({
    key: 'a',
    label: 'a',
    color: '#000',
    data,
    ...overrides,
})

describe('goalLinesAdapter', () => {
    describe('computeSeriesNonZeroMax', () => {
        it('returns the max non-zero finite value across all series', () => {
            const result = computeSeriesNonZeroMax([makeSeries([1, 2, 0, 5]), makeSeries([0, 0, 3, NaN])])
            expect(result).toBe(5)
        })

        it('ignores hidden series', () => {
            const result = computeSeriesNonZeroMax([
                makeSeries([1, 2, 3]),
                makeSeries([1000], { key: 'b', visibility: { excluded: true } }),
            ])
            expect(result).toBe(3)
        })

        it('returns 0 when no series have non-zero values', () => {
            expect(computeSeriesNonZeroMax([makeSeries([0, 0, NaN])])).toBe(0)
            expect(computeSeriesNonZeroMax([])).toBe(0)
        })
    })

    describe('goalLinesToReferenceLines', () => {
        const series = [makeSeries([10, 20, 30])]

        it('returns an empty array for nullish/empty input', () => {
            expect(goalLinesToReferenceLines(null, series)).toEqual([])
            expect(goalLinesToReferenceLines(undefined, series)).toEqual([])
            expect(goalLinesToReferenceLines([], series)).toEqual([])
        })

        it('maps each goal to a ReferenceLine with variant "goal"', () => {
            const goals: SchemaGoalLine[] = [{ label: 'Target', value: 50 }]
            const result = goalLinesToReferenceLines(goals, series)
            expect(result).toHaveLength(1)
            expect(result[0]).toMatchObject({
                value: 50,
                orientation: 'horizontal',
                variant: 'goal',
                label: 'Target',
                labelPosition: 'start',
            })
        })

        it.each([
            [
                'propagates borderColor via style.color',
                { borderColor: 'var(--danger)' },
                { style: { color: 'var(--danger)' } },
            ],
            ['omits label when displayLabel is false', { displayLabel: false }, { label: undefined }],
            ['respects explicit labelPosition', { position: 'end' }, { labelPosition: 'end' }],
        ] as const)('%s', (_, goalOverrides, expectedProps) => {
            const goals: SchemaGoalLine[] = [{ label: 'X', value: 50, ...goalOverrides }]
            expect(goalLinesToReferenceLines(goals, series)[0]).toMatchObject(expectedProps)
        })

        it('drops goals when displayIfCrossed=false and value is below the series peak', () => {
            const goals: SchemaGoalLine[] = [
                { label: 'Crossed', value: 5, displayIfCrossed: false },
                { label: 'Uncrossed', value: 100, displayIfCrossed: false },
            ]
            const result = goalLinesToReferenceLines(goals, series) // seriesMax = 30
            expect(result.map((r) => r.label)).toEqual(['Uncrossed'])
        })

        it('keeps goals when displayIfCrossed is undefined or true', () => {
            const goals: SchemaGoalLine[] = [
                { label: 'Default', value: 5 },
                { label: 'Explicit', value: 5, displayIfCrossed: true },
            ]
            const result = goalLinesToReferenceLines(goals, series)
            expect(result).toHaveLength(2)
        })
    })

    describe('alertThresholdsToReferenceLines', () => {
        it('returns an empty array for nullish/empty input', () => {
            expect(alertThresholdsToReferenceLines(null)).toEqual([])
            expect(alertThresholdsToReferenceLines(undefined)).toEqual([])
            expect(alertThresholdsToReferenceLines([])).toEqual([])
        })

        it('maps each threshold to a ReferenceLine with variant "alert"', () => {
            const lines: SchemaGoalLine[] = [
                { label: 'Upper', value: 100 },
                { label: 'Lower', value: 10 },
            ]
            const result = alertThresholdsToReferenceLines(lines)
            expect(result).toHaveLength(2)
            expect(result[0]).toMatchObject({
                value: 100,
                orientation: 'horizontal',
                variant: 'alert',
                label: 'Upper',
                labelPosition: 'start',
            })
            expect(result[1]).toMatchObject({ value: 10, variant: 'alert' })
        })

        it('does not apply the displayIfCrossed filter (always renders thresholds)', () => {
            const lines: SchemaGoalLine[] = [
                { label: 'Crossed', value: 1, displayIfCrossed: false },
                { label: 'Above', value: 9999, displayIfCrossed: false },
            ]
            expect(alertThresholdsToReferenceLines(lines).map((r) => r.label)).toEqual(['Crossed', 'Above'])
        })
    })
})
