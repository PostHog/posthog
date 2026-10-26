import { CachedNewExperimentQueryResponse } from '~/queries/schema/schema-general'

import type { RunningTimeOutlookApi } from 'products/experiments/frontend/generated/api.schemas'

import {
    buildRunningTimeOutlook,
    calculateCurrentExposures,
    calculateDaysElapsed,
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
                targetSampleSize: 35556,
                minimumDetectableEffect: 30,
                currentExposures: 2000,
                remainingDays: null,
                ...overrides,
            })

        it('places the target on the remaining days, among today and the week marks', () => {
            const result = outlook({ remainingDays: 235 })!

            expect(
                result.checkpoints.map(({ kind, days, detectableEffect }) => [kind, days, detectableEffect])
            ).toEqual([
                ['now', 14, 126.5],
                ['week', 28, 89.4],
                ['week', 42, 73],
                ['week', 56, 63.2],
                ['target', 249, 30],
            ])
            expect(result.daysToTarget).toBeCloseTo(248.9, 1)
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
            ['no target', { targetSampleSize: null }],
        ])('gives no outlook without %s', (_name, overrides) => {
            expect(outlook(overrides)).toBeNull()
        })
    })

    describe('formatDetectableEffect', () => {
        it.each([
            [126.49, '127%'],
            [30.000000001, '30%'],
            [8.71, '8.8%'],
        ])('rounds the detectable change %s up to %s', (detectableEffect, formatted) => {
            expect(formatDetectableEffect(detectableEffect)).toEqual(formatted)
        })
    })
})
