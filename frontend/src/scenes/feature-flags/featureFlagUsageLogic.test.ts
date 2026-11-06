import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import { featureFlagUsageLogic } from './featureFlagUsageLogic'
import { DEFAULT_USAGE_DATE_RANGE, FlagUsageQuery } from './featureFlagUsageQueries'

const FLAG_ID = 1

function setFlagEvaluationsMode(mode: FlagEvaluationsModeEnumApi): void {
    teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: mode })
}

// Every chart reads the events table unless a test moves the team off the Events mode.
function trendsSource(query: FlagUsageQuery): TrendsQuery {
    if (query.kind !== NodeKind.InsightVizNode) {
        throw new Error(`Expected an events-table trend, got ${query.kind}`)
    }
    return query.source
}

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
        ['events', FlagEvaluationsModeEnumApi.Number0, false],
        ['read flag evaluations', FlagEvaluationsModeEnumApi.Number1, true],
        ['flag evaluations only', FlagEvaluationsModeEnumApi.Number2, true],
    ])('reads flag_evaluations for the %s mode: %s', (_name, mode, readsEvaluations) => {
        setFlagEvaluationsMode(mode)

        expect(logic.values.readsFlagEvaluationsTable).toEqual(readsEvaluations)
        expect(logic.values.usageCharts.map((chart) => chart.query.kind)).toEqual(
            readsEvaluations
                ? [NodeKind.DataVisualizationNode, NodeKind.DataVisualizationNode]
                : [NodeKind.InsightVizNode, NodeKind.InsightVizNode]
        )
    })

    it('holds the date range inside the retention window when reading flag_evaluations', async () => {
        setFlagEvaluationsMode(FlagEvaluationsModeEnumApi.Number1)

        await expectLogic(logic, () => {
            logic.actions.setDates('-180d', null)
        }).toMatchValues({
            selectedDateRange: { date_from: '-180d', date_to: null },
            dateRange: { date_from: '-90d', date_to: null },
        })

        const optionKeys = logic.values.dateOptions?.map((option) => option.key)
        expect(optionKeys).toContain('Last 90 days')
        expect(optionKeys).not.toContain('All time')
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
            expect(trendsSource(chart.query).dateRange).toEqual({ date_from: '-24h', date_to: null })
            expect(trendsSource(chart.query).interval).toEqual('hour')
        }
    })

    it('carries the flag key into every chart query', () => {
        featureFlagLogic({ id: FLAG_ID }).actions.loadFeatureFlagSuccess(flag({ key: 'renamed-feature' }))

        for (const chart of logic.values.usageCharts) {
            expect(trendsSource(chart.query).properties).toEqual([
                expect.objectContaining({ value: 'renamed-feature' }),
            ])
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
