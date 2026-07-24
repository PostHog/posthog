import type { GuardAvailableFeatureFn } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { dayjs } from 'lib/dayjs'
import { userLogic } from 'scenes/userLogic'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import {
    expectedFirstAlertEvaluation,
    getDefaultSimulationRange,
    isSubDailyAlertInterval,
    selectAlertCalculationInterval,
} from './alertIntervalHelpers'

describe('alertIntervalHelpers', () => {
    beforeEach(() => {
        initKeaTests()
    })

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

    describe('expectedFirstAlertEvaluation', () => {
        it.each([
            [AlertCalculationInterval.REAL_TIME, '2026-07-24T16:30:00.000Z', '2026-07-24T16:32:00.000Z'],
            [AlertCalculationInterval.EVERY_15_MINUTES, '2026-07-24T16:30:00.000Z', '2026-07-24T16:45:00.000Z'],
            [AlertCalculationInterval.HOURLY, '2026-07-24T16:30:00.000Z', '2026-07-24T17:30:00.000Z'],
            [AlertCalculationInterval.DAILY, '2026-07-24T16:30:00.000Z', '2026-07-25T05:00:00.000Z'],
            [AlertCalculationInterval.WEEKLY, '2026-07-24T16:30:00.000Z', '2026-07-27T07:00:00.000Z'],
            [AlertCalculationInterval.WEEKLY, '2026-07-27T16:30:00.000Z', '2026-08-03T07:00:00.000Z'],
            [AlertCalculationInterval.MONTHLY, '2026-07-24T16:30:00.000Z', '2026-08-01T08:00:00.000Z'],
        ])('%s from %s matches the backend first-run schedule', (interval, current, expected) => {
            const currentTime = dayjs(current)
            expect(expectedFirstAlertEvaluation(interval, 'America/New_York', currentTime).toISOString()).toBe(expected)
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
})
