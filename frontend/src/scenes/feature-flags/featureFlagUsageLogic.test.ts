import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import { featureFlagUsageLogic } from './featureFlagUsageLogic'
import { DEFAULT_USAGE_DATE_RANGE } from './featureFlagUsageQueries'

const FLAG_ID = 1

function flag(overrides: Partial<FeatureFlagType> = {}): FeatureFlagType {
    return {
        ...NEW_FLAG,
        id: FLAG_ID,
        key: 'alpha-feature',
        has_enriched_analytics: false,
        ...overrides,
    }
}

describe('featureFlagUsageLogic', () => {
    let logic: ReturnType<typeof featureFlagUsageLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                [`/api/projects/:team/feature_flags/${FLAG_ID}/`]: () => [200, flag()],
            },
        })
        initKeaTests()
        featureFlagLogic({ id: FLAG_ID }).mount()
        logic = featureFlagUsageLogic({ id: FLAG_ID })
        logic.mount()
    })

    it.each([
        [false, ['total-volume', 'unique-callers']],
        [true, ['total-volume', 'unique-callers', 'feature-view', 'feature-interaction']],
    ])('renders the enriched charts only when has_enriched_analytics is %s', (hasEnriched, expectedKeys) => {
        featureFlagLogic({ id: FLAG_ID }).actions.loadFeatureFlagSuccess(flag({ has_enriched_analytics: hasEnriched }))

        expect(logic.values.usageCharts.map((chart) => chart.key)).toEqual(expectedKeys)
    })

    it('rebuilds every chart against the selected date range', async () => {
        featureFlagLogic({ id: FLAG_ID }).actions.loadFeatureFlagSuccess(flag({ has_enriched_analytics: true }))

        await expectLogic(logic, () => {
            logic.actions.setDates('-24h', null)
        }).toMatchValues({ dateRange: { date_from: '-24h', date_to: null } })

        expect(logic.values.usageCharts).toHaveLength(4)
        for (const chart of logic.values.usageCharts) {
            expect(chart.query.source.dateRange).toEqual({ date_from: '-24h', date_to: null })
            expect(chart.query.source.interval).toEqual('hour')
        }
    })

    it('carries the flag key into every chart query', () => {
        featureFlagLogic({ id: FLAG_ID }).actions.loadFeatureFlagSuccess(flag({ key: 'renamed-feature' }))

        for (const chart of logic.values.usageCharts) {
            expect(chart.query.source.properties).toEqual([expect.objectContaining({ value: 'renamed-feature' })])
        }
    })

    it('writes the selected range to the URL without pushing a history entry', async () => {
        router.actions.push(urls.featureFlag(FLAG_ID))

        await expectLogic(logic, () => {
            logic.actions.setDates('-7d', null)
        }).toFinishAllListeners()

        expect(router.values.searchParams).toMatchObject({ date_from: '-7d' })
        expect(router.values.searchParams.date_to).toBeUndefined()
        // A push here would make featureFlagLogic reload the flag on every date change.
        expect(router.values.lastMethod).toEqual('REPLACE')
    })

    it('restores the range from the URL', async () => {
        await expectLogic(logic, () => {
            router.actions.push(urls.featureFlag(FLAG_ID), { date_from: '-24h' })
        }).toMatchValues({ dateRange: { date_from: '-24h', date_to: null } })
    })

    it('treats a URL with only date_to as an explicit range, not the default', async () => {
        await expectLogic(logic, () => {
            router.actions.push(urls.featureFlag(FLAG_ID), { date_to: '2024-01-01' })
        }).toMatchValues({ dateRange: { date_from: null, date_to: '2024-01-01' } })
    })

    it('keeps the default range when the URL carries no date params', async () => {
        await expectLogic(logic, () => {
            router.actions.push(urls.featureFlag(FLAG_ID), { edit: 'true' })
        }).toMatchValues({ dateRange: DEFAULT_USAGE_DATE_RANGE })
    })

    it('resets a custom range back to default when navigating to a bare URL', async () => {
        await expectLogic(logic, () => {
            logic.actions.setDates('-7d', null)
        }).toMatchValues({ dateRange: { date_from: '-7d', date_to: null } })

        await expectLogic(logic, () => {
            router.actions.push(urls.featureFlag(FLAG_ID))
        }).toMatchValues({ dateRange: DEFAULT_USAGE_DATE_RANGE })
    })
})
