import { dayjs } from 'lib/dayjs'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import {
    approximateNextAlertRun,
    isNextPlannedEvaluationStale,
    normalizeScheduleRestrictionForCompare,
    type SchedulingSnapshot,
} from './alertSchedulingStale'

describe('alertSchedulingStale', () => {
    describe('approximateNextAlertRun', () => {
        it.each([
            [AlertCalculationInterval.REAL_TIME, '2026-07-24T16:02:00.000Z'],
            [AlertCalculationInterval.EVERY_15_MINUTES, '2026-07-24T16:15:00.000Z'],
            [AlertCalculationInterval.HOURLY, '2026-07-24T17:00:00.000Z'],
            [AlertCalculationInterval.DAILY, '2026-07-25T05:00:00.000Z'],
            [AlertCalculationInterval.WEEKLY, '2026-07-27T07:00:00.000Z'],
            [AlertCalculationInterval.MONTHLY, '2026-08-01T08:00:00.000Z'],
        ])('matches the backend anchor for %s', (interval, expected) => {
            const now = dayjs.utc('2026-07-24T16:00:00.000Z')

            expect(approximateNextAlertRun(interval, 'America/Toronto', now).toISOString()).toBe(expected)
        })
    })

    describe('normalizeScheduleRestrictionForCompare', () => {
        it('maps missing, null, and empty windows to null', () => {
            expect(normalizeScheduleRestrictionForCompare(undefined)).toBeNull()
            expect(normalizeScheduleRestrictionForCompare(null)).toBeNull()
            expect(normalizeScheduleRestrictionForCompare({ blocked_windows: [] })).toBeNull()
        })

        it('preserves non-empty windows', () => {
            const sr = { blocked_windows: [{ start: '22:00', end: '07:00' }] }
            expect(normalizeScheduleRestrictionForCompare(sr)).toEqual(sr)
        })
    })

    describe('isNextPlannedEvaluationStale', () => {
        const saved: SchedulingSnapshot = {
            calculation_interval: AlertCalculationInterval.DAILY,
            schedule_restriction: null,
            skip_weekend: false,
            config: { check_ongoing_interval: false },
        }

        it('is false when creating a new alert', () => {
            expect(
                isNextPlannedEvaluationStale(true, saved, {
                    calculation_interval: AlertCalculationInterval.HOURLY,
                })
            ).toBe(false)
        })

        it('is false when saved alert is missing', () => {
            expect(
                isNextPlannedEvaluationStale(false, undefined, {
                    calculation_interval: AlertCalculationInterval.DAILY,
                })
            ).toBe(false)
        })

        it.each([
            [
                'calculation_interval',
                {
                    calculation_interval: AlertCalculationInterval.HOURLY,
                    schedule_restriction: null,
                    skip_weekend: false,
                    config: { check_ongoing_interval: false },
                },
                true,
            ],
            [
                'schedule_restriction',
                {
                    calculation_interval: AlertCalculationInterval.DAILY,
                    schedule_restriction: { blocked_windows: [{ start: '22:00', end: '07:00' }] },
                    skip_weekend: false,
                    config: { check_ongoing_interval: false },
                },
                true,
            ],
            [
                'skip_weekend',
                {
                    calculation_interval: AlertCalculationInterval.DAILY,
                    schedule_restriction: null,
                    skip_weekend: true,
                    config: { check_ongoing_interval: false },
                },
                true,
            ],
            [
                'check_ongoing_interval',
                {
                    calculation_interval: AlertCalculationInterval.DAILY,
                    schedule_restriction: null,
                    skip_weekend: false,
                    config: { check_ongoing_interval: true },
                },
                true,
            ],
        ])('is true when %s differs from saved', (_label, form, expected) => {
            expect(isNextPlannedEvaluationStale(false, saved, form)).toBe(expected)
        })

        it('is false when form matches saved (null vs empty quiet hours)', () => {
            expect(
                isNextPlannedEvaluationStale(false, saved, {
                    calculation_interval: AlertCalculationInterval.DAILY,
                    schedule_restriction: { blocked_windows: [] },
                    skip_weekend: false,
                    config: { check_ongoing_interval: false },
                })
            ).toBe(false)
        })

        it('is false when normalized schedule matches', () => {
            const sr = { blocked_windows: [{ start: '10:00', end: '11:00' }] }
            expect(
                isNextPlannedEvaluationStale(
                    false,
                    { ...saved, schedule_restriction: sr },
                    { ...saved, schedule_restriction: { blocked_windows: [{ start: '10:00', end: '11:00' }] } }
                )
            ).toBe(false)
        })
    })
})
