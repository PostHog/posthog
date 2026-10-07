import type { GuardAvailableFeatureFn } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { dayjs } from 'lib/dayjs'
import { userLogic } from 'scenes/userLogic'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import {
    evaluationDelayPreview,
    canSetAlertScheduleStartTime,
    getAlertScheduleStartMinute,
    getDefaultSimulationRange,
    isSubDailyAlertInterval,
    selectAlertCalculationInterval,
    scheduleStartTimeForInterval,
    scheduleStartTimeForMinute,
} from './alertIntervalHelpers'

describe('alertIntervalHelpers', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        ['hour', 0, 'UTC', 0, '2026-09-29T10:30:00Z', 'Sep 29, 2026 09:00 +00:00 to Sep 29, 2026 10:00 +00:00'],
        ['hour', 2, 'UTC', 0, '2026-09-29T10:30:00Z', 'Sep 29, 2026 07:00 +00:00 to Sep 29, 2026 08:00 +00:00'],
        [
            'day',
            1,
            'America/New_York',
            0,
            '2026-03-10T12:00:00Z',
            'Mar 8, 2026 00:00 -05:00 to Mar 9, 2026 00:00 -04:00',
        ],
        [
            'hour',
            1,
            'America/New_York',
            0,
            '2026-11-01T07:30:00Z',
            'Nov 1, 2026 01:00 -04:00 to Nov 1, 2026 01:00 -05:00',
        ],
        ['month', 1, 'UTC', 0, '2026-03-15T12:00:00Z', 'Jan 1, 2026 00:00 +00:00 to Feb 1, 2026 00:00 +00:00'],
        ['week', 1, 'UTC', 1, '2026-09-29T10:30:00Z', 'Sep 14, 2026 00:00 +00:00 to Sep 21, 2026 00:00 +00:00'],
    ] as const)(
        'previews the eligible %s interval with delay %s in %s',
        (interval, delay, timezone, weekStart, now, expected) => {
            expect(evaluationDelayPreview(interval, delay, timezone, weekStart, dayjs(now))).toBe(expected)
        }
    )

    describe('getDefaultSimulationRange', () => {
        it.each([
            [AlertCalculationInterval.REAL_TIME, '-1h'],
            [AlertCalculationInterval.EVERY_15_MINUTES, '-12h'],
            [AlertCalculationInterval.HOURLY, '-48h'],
            [AlertCalculationInterval.DAILY, '-30d'],
            [AlertCalculationInterval.WEEKLY, '-12w'],
            [AlertCalculationInterval.MONTHLY, '-12m'],
        ])('%s returns %s', (interval, expected) => {
            expect(getDefaultSimulationRange(interval)).toBe(expected)
        })
    })

    describe('selectAlertCalculationInterval', () => {
        beforeEach(() => {
            userLogic.mount()
            upgradeModalLogic.mount()
        })

        it('opens upgrade modal and does not update interval when 15-minute is selected without entitlement', () => {
            const onSelect = jest.fn()

            const applied = selectAlertCalculationInterval(AlertCalculationInterval.EVERY_15_MINUTES, {
                guardAvailableFeature: upgradeModalLogic.values.guardAvailableFeature,
                onSelect,
                hasHighFrequencyAlertsEntitlement: false,
                hasRealTimeAlertsEntitlement: false,
            })

            expect(applied).toBe(false)
            expect(onSelect).not.toHaveBeenCalled()
            expect(upgradeModalLogic.values.upgradeModalFeatureKey).toBe(AvailableFeature.HIGH_FREQUENCY_ALERTS)
        })

        it('opens upgrade modal and does not update interval when real time is selected without entitlement', () => {
            const onSelect = jest.fn()

            const applied = selectAlertCalculationInterval(AlertCalculationInterval.REAL_TIME, {
                guardAvailableFeature: upgradeModalLogic.values.guardAvailableFeature,
                onSelect,
                hasHighFrequencyAlertsEntitlement: false,
                hasRealTimeAlertsEntitlement: false,
            })

            expect(applied).toBe(false)
            expect(onSelect).not.toHaveBeenCalled()
            expect(upgradeModalLogic.values.upgradeModalFeatureKey).toBe(AvailableFeature.REAL_TIME_ALERTS)
        })

        it('updates interval when 15-minute is selected with entitlement', () => {
            const onSelect = jest.fn()
            const guardAvailableFeature: GuardAvailableFeatureFn = (_feature, callback) => {
                callback?.()
                return true
            }

            const applied = selectAlertCalculationInterval(AlertCalculationInterval.EVERY_15_MINUTES, {
                guardAvailableFeature,
                onSelect,
                hasHighFrequencyAlertsEntitlement: true,
                hasRealTimeAlertsEntitlement: false,
            })

            expect(applied).toBe(true)
            expect(onSelect).toHaveBeenCalledWith(AlertCalculationInterval.EVERY_15_MINUTES)
        })

        it('updates interval when real time is selected with entitlement', () => {
            const onSelect = jest.fn()
            const guardAvailableFeature: GuardAvailableFeatureFn = (_feature, callback) => {
                callback?.()
                return true
            }

            const applied = selectAlertCalculationInterval(AlertCalculationInterval.REAL_TIME, {
                guardAvailableFeature,
                onSelect,
                hasHighFrequencyAlertsEntitlement: false,
                hasRealTimeAlertsEntitlement: true,
            })

            expect(applied).toBe(true)
            expect(onSelect).toHaveBeenCalledWith(AlertCalculationInterval.REAL_TIME)
        })

        it('updates interval for non-15-minute options without calling the guard', () => {
            const onSelect = jest.fn()
            const guardAvailableFeature = jest.fn<
                ReturnType<GuardAvailableFeatureFn>,
                Parameters<GuardAvailableFeatureFn>
            >(() => true)

            selectAlertCalculationInterval(AlertCalculationInterval.HOURLY, {
                guardAvailableFeature,
                onSelect,
                hasHighFrequencyAlertsEntitlement: false,
                hasRealTimeAlertsEntitlement: false,
            })

            expect(onSelect).toHaveBeenCalledWith(AlertCalculationInterval.HOURLY)
            expect(guardAvailableFeature).not.toHaveBeenCalled()
        })
    })

    describe('isSubDailyAlertInterval', () => {
        it.each([
            [AlertCalculationInterval.REAL_TIME, true],
            [AlertCalculationInterval.EVERY_15_MINUTES, true],
            [AlertCalculationInterval.HOURLY, true],
            [AlertCalculationInterval.DAILY, false],
            [AlertCalculationInterval.WEEKLY, false],
            [AlertCalculationInterval.MONTHLY, false],
        ])('%s → %s', (interval, expected) => {
            expect(isSubDailyAlertInterval(interval)).toBe(expected)
        })
    })

    describe('canSetAlertScheduleStartTime', () => {
        it.each([
            [AlertCalculationInterval.REAL_TIME, false],
            [AlertCalculationInterval.EVERY_15_MINUTES, false],
            [AlertCalculationInterval.HOURLY, true],
            [AlertCalculationInterval.DAILY, false],
            [AlertCalculationInterval.WEEKLY, false],
            [AlertCalculationInterval.MONTHLY, false],
        ])('%s → %s', (interval, expected) => {
            expect(canSetAlertScheduleStartTime(interval)).toBe(expected)
        })
    })

    describe('schedule start time for interval', () => {
        it.each([
            [AlertCalculationInterval.EVERY_15_MINUTES, null],
            [AlertCalculationInterval.HOURLY, '00:55'],
            [AlertCalculationInterval.REAL_TIME, null],
            [AlertCalculationInterval.DAILY, null],
            [AlertCalculationInterval.WEEKLY, null],
            [AlertCalculationInterval.MONTHLY, null],
        ])('uses %s → %s', (interval, expected) => {
            expect(scheduleStartTimeForInterval(interval, '00:55')).toBe(expected)
        })

        it.each([[AlertCalculationInterval.HOURLY, null]])(
            'preserves an unanchored %s schedule',
            (interval, expected) => {
                expect(scheduleStartTimeForInterval(interval, null)).toBe(expected)
            }
        )
    })

    describe('alert schedule start minute', () => {
        it.each([
            [undefined, undefined],
            [null, undefined],
            ['08:57', 57],
            ['00:03', 3],
        ])('reads %s as %s', (scheduleStartTime, expected) => {
            expect(getAlertScheduleStartMinute(scheduleStartTime)).toBe(expected)
        })

        it.each([
            [undefined, null],
            [Number.NaN, null],
            [1.5, null],
            [-1, null],
            [60, null],
            [0, '00:00'],
            [12, '00:12'],
            [55, '00:55'],
            [57, '00:57'],
        ])('writes %s as %s', (minute, expected) => {
            expect(scheduleStartTimeForMinute(minute)).toBe(expected)
        })
    })
})
