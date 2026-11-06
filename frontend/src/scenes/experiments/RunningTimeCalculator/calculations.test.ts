import { CachedNewExperimentQueryResponse } from '~/queries/schema/schema-general'

import type { RunningTimeOutlookApi } from 'products/experiments/frontend/generated/api.schemas'

import {
    buildRunningTimeOutlook,
    calculateCurrentExposures,
    calculateDaysElapsed,
    DetectableEffectCheckpoint,
    describeCheckpointDay,
    describeUseButton,
    formatDetectableEffect,
    RunningTimeOutlook,
} from './calculations'

// The sample-size / variance math is verified in the backend
// (products/experiments/backend/test/test_running_time_calculator.py). These tests
// cover the client-side helpers that read live experiment state.
describe('running time calculations', () => {
    describe('calculateCurrentExposures', () => {
        it('sums baseline and variant sample counts', () => {
            const results = {
                baseline: { number_of_samples: 1000 },
                variant_results: [{ number_of_samples: 900 }, { number_of_samples: 1100 }],
            } as CachedNewExperimentQueryResponse
            expect(calculateCurrentExposures(results)).toBe(3000)
        })

        it('returns null without results', () => {
            expect(calculateCurrentExposures(null)).toBeNull()
        })
    })

    describe('calculateDaysElapsed', () => {
        it('returns null without a start date', () => {
            expect(calculateDaysElapsed(null)).toBeNull()
        })

        it('returns a positive number for a past start date', () => {
            const elapsed = calculateDaysElapsed('2020-01-01')
            expect(elapsed).not.toBeNull()
            expect(elapsed!).toBeGreaterThan(0)
        })
    })

    describe('buildRunningTimeOutlook', () => {
        // Two weeks in at about 143 exposures a day, as the backend projects it.
        const PROJECTION: RunningTimeOutlookApi = {
            days_since_launch: 14,
            exposures_per_day: 2000 / 14,
            detectable_effect_now: 126.5,
            upcoming_checkpoints: [
                { weeks_since_launch: 4, detectable_effect: 89.4 },
                { weeks_since_launch: 6, detectable_effect: 73 },
                { weeks_since_launch: 8, detectable_effect: 63.2 },
            ],
            reachable_effect: 73,
        }
        const outlook = (
            overrides: Partial<Parameters<typeof buildRunningTimeOutlook>[0]>
        ): RunningTimeOutlook | null =>
            buildRunningTimeOutlook({
                projection: PROJECTION,
                currentSampleSize: 2000,
                savedEffect: 30,
                savedSampleSize: 35556,
                defaultEffect: 30,
                enteredEffect: null,
                selectedKey: null,
                minimumDetectableEffect: 30,
                ...overrides,
            })
        const rowsOf = (result: RunningTimeOutlook): string[] =>
            result.checkpoints.map(({ kind, isTarget }) => (isTarget ? `${kind} (target)` : kind))

        it('lays out today, the week marks and the custom row at the saved effect', () => {
            const result = outlook({})!

            expect(
                result.checkpoints.map(({ kind, days, exposures, detectableEffect, isTarget }) => [
                    kind,
                    Math.round(days),
                    exposures,
                    detectableEffect,
                    isTarget,
                ])
            ).toEqual([
                ['now', 14, 2000, 126.5, false],
                ['week', 28, 4000, 89.4, false],
                ['week', 42, 6000, 73, false],
                ['week', 56, 8000, 63.2, false],
                ['custom', 249, 35556, 30, true],
            ])
            expect(result.daysToTarget).toBeCloseTo(248.9, 1)
        })

        it.each([
            [
                '"Use" chooses a week mark',
                { selectedKey: 'week-6' },
                ['now', 'week', 'week (target)', 'week', 'custom'],
                30,
                42,
            ],
            ['"Use" chooses today', { selectedKey: 'now' }, ['now (target)', 'week', 'week', 'week', 'custom'], 30, 14],
            [
                'the slider moves the custom row',
                { enteredEffect: 50 },
                ['now', 'week', 'week', 'week', 'custom (target)'],
                50,
                89.6,
            ],
        ])('keeps the same rows when %s', (_name, overrides, rows, customEffect, daysToTarget) => {
            const result = outlook(overrides)!

            expect(rowsOf(result)).toEqual(rows)
            expect(result.checkpoints.find(({ kind }) => kind === 'custom')?.detectableEffect).toEqual(customEffect)
            expect(result.daysToTarget).toBeCloseTo(daysToTarget, 1)
        })

        it('reopens on the row whose effect was saved, with the custom row at the default effect', () => {
            const result = outlook({ savedEffect: 73, savedSampleSize: 5990, minimumDetectableEffect: 73 })!

            expect(rowsOf(result)).toEqual(['now', 'week', 'week (target)', 'week', 'custom'])
            expect(result.checkpoints.find(({ kind }) => kind === 'custom')?.detectableEffect).toEqual(30)
        })

        it.each([
            [80, false],
            [73, false],
            [30, true],
        ])('puts a %s%% target out of reach: %s', (minimumDetectableEffect, isOutOfReach) => {
            expect(outlook({ minimumDetectableEffect })!.isOutOfReach).toBe(isOutOfReach)
        })

        it.each([
            ['no projection', { projection: null }],
            ['no saved target', { savedSampleSize: null }],
            ['no exposures so far', { currentSampleSize: null }],
        ])('gives no outlook without %s', (_name, overrides) => {
            expect(outlook(overrides)).toBeNull()
        })
    })

    describe('describeCheckpointDay', () => {
        const checkpoint = (overrides: Partial<DetectableEffectCheckpoint>): DetectableEffectCheckpoint => ({
            key: 'custom',
            kind: 'custom',
            days: 18,
            exposures: 3341,
            detectableEffect: 30,
            isTarget: false,
            ...overrides,
        })

        beforeEach(() => {
            jest.useFakeTimers().setSystemTime(new Date('2026-10-27T12:00:00Z'))
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it.each([
            ['a week mark', { kind: 'week' as const, days: 14 }, 'week 2'],
            ['today', { kind: 'now' as const, days: 11.17, exposures: 2000 }, 'day 12'],
            ['the custom row before it is reached', {}, 'in 7 days'],
            ['the custom row reached earlier today', { days: 11, exposures: 1970 }, 'day 12'],
        ])('describes %s', (_name, overrides, description) => {
            expect(
                describeCheckpointDay(checkpoint(overrides), {
                    startDate: '2026-10-16T08:00:00Z',
                    currentSampleSize: 2000,
                })
            ).toEqual(description)
        })
    })

    describe('describeUseButton', () => {
        it.each([
            [
                'the effect of a week mark as the table shows it',
                { kind: 'week' as const, detectableEffect: 32.74 },
                { effect: 32.8, tooltip: 'Set 32.8% as the minimum detectable effect' },
            ],
            [
                'the custom effect as it is',
                { kind: 'custom' as const, detectableEffect: 12.345 },
                { effect: 12.345, tooltip: 'Set 12.345% as the minimum detectable effect' },
            ],
            [
                'only why an effect over 100% cannot be set',
                { kind: 'now' as const, detectableEffect: 126.5 },
                { effect: 127, disabledReason: 'The minimum detectable effect can be at most 100%' },
            ],
        ])('offers %s', (_name, overrides, button) => {
            expect(describeUseButton({ key: 'row', days: 14, exposures: 2000, isTarget: false, ...overrides })).toEqual(
                button
            )
        })
    })

    describe('formatDetectableEffect', () => {
        it.each([
            [63.21, '63.3%'],
            [30.000000001, '30%'],
            [8.714, '8.72%'],
            [100, '100%'],
            [100.01, '>100%'],
            [126.49, '>100%'],
        ])('formats the detectable change %s as %s', (detectableEffect, formatted) => {
            expect(formatDetectableEffect(detectableEffect)).toEqual(formatted)
        })
    })
})
