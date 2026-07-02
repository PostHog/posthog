import type { GuardAvailableFeatureFn } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { userLogic } from 'scenes/userLogic'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import {
    getDefaultSimulationRange,
    isHighFrequencyAlertInterval,
    selectAlertCalculationInterval,
} from './alertIntervalHelpers'

describe('alertIntervalHelpers', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('getDefaultSimulationRange', () => {
        it.each([
            [AlertCalculationInterval.REAL_TIME, '-2h'],
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

    describe('isHighFrequencyAlertInterval', () => {
        it.each([
            [AlertCalculationInterval.REAL_TIME, true],
            [AlertCalculationInterval.EVERY_15_MINUTES, true],
            [AlertCalculationInterval.HOURLY, true],
            [AlertCalculationInterval.DAILY, false],
            [AlertCalculationInterval.WEEKLY, false],
            [AlertCalculationInterval.MONTHLY, false],
        ])('%s → %s', (interval, expected) => {
            expect(isHighFrequencyAlertInterval(interval)).toBe(expected)
        })
    })
})
