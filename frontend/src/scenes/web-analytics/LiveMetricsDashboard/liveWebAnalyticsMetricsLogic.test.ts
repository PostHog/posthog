import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { initKeaTests } from '~/test/init'
import { AvailableFeature, LiveEvent } from '~/types'

import { liveWebAnalyticsMetricsLogic } from './liveWebAnalyticsMetricsLogic'

const CLASSES_RULE = { alias: '/classes/:id', regex: '/classes/[^/]+', order: 0 }

const pageview = (pathname: string, distinctId: string): LiveEvent => ({
    uuid: `${distinctId}-${pathname}`,
    event: '$pageview',
    properties: { $pathname: pathname, $device_id: distinctId },
    timestamp: new Date().toISOString(),
    team_id: MOCK_DEFAULT_TEAM.id,
    distinct_id: distinctId,
    created_at: new Date().toISOString(),
})

describe('liveWebAnalyticsMetricsLogic', () => {
    let logic: ReturnType<typeof liveWebAnalyticsMetricsLogic.build>

    beforeEach(() => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, path_cleaning_filters: [CLASSES_RULE] }, MOCK_DEFAULT_PROJECT, {
            ...MOCK_DEFAULT_ORGANIZATION,
            available_product_features: [
                { key: AvailableFeature.PATHS_ADVANCED, name: AvailableFeature.PATHS_ADVANCED },
            ],
        })
        jest.spyOn(api, 'query').mockResolvedValue({ results: [] } as any)
        ;(posthog as any).setPersonProperties = jest.fn()
        logic = liveWebAnalyticsMetricsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('collapses streamed pageviews that clean to the same path into one row', () => {
        logic.actions.addEvents(
            [pageview('/classes/928q3hr9paw8hfe', 'user-1'), pageview('/classes/j2k4l6m8n0p', 'user-2')],
            new Date(Date.now() - 60_000),
            logic.values.pathCleaningFilters
        )

        expect(logic.values.topPaths).toEqual([{ path: '/classes/:id', views: 2 }])
    })

    it('leaves streamed paths untouched once path cleaning is switched off', () => {
        webAnalyticsLogic.actions.setIsPathCleaningEnabled(false)

        logic.actions.addEvents(
            [pageview('/classes/928q3hr9paw8hfe', 'user-1')],
            new Date(Date.now() - 60_000),
            logic.values.pathCleaningFilters
        )

        expect(logic.values.topPaths).toEqual([{ path: '/classes/928q3hr9paw8hfe', views: 1 }])
    })

    it('queues a reload for a path cleaning change that lands during the initial load', async () => {
        // Rebuild the logic against a gated query mock so the initial load stays in flight.
        logic.unmount()
        let openGate: () => void = () => {}
        const gate = new Promise<void>((resolve) => {
            openGate = resolve
        })
        jest.spyOn(api, 'query').mockImplementation(async () => {
            await gate
            return { results: [] } as any
        })
        logic = liveWebAnalyticsMetricsLogic()
        logic.mount()

        // The in-flight load captured the old setting; this change must not be dropped.
        webAnalyticsLogic.actions.setIsPathCleaningEnabled(!webAnalyticsLogic.values.isPathCleaningEnabled)
        openGate()

        await expectLogic(logic).toDispatchActions(['scheduleReload', 'loadInitialData'])
    })

    it('does not run the expensive bot query while bot analysis is disabled', async () => {
        await expectLogic(logic).toDispatchActions(['setInitialData'])

        const queries = JSON.stringify((api.query as jest.Mock).mock.calls)
        expect(queries).not.toContain('counts_by_bot')
        expect(queries).toContain('bot_eligible_events')
    })

    it('runs the bot query after the core tiles when bot analysis is enabled', async () => {
        logic.unmount()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS], {
            [FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS]: true,
        })
        logic = liveWebAnalyticsMetricsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['setInitialData', 'setBotData'])

        expect(JSON.stringify((api.query as jest.Mock).mock.calls)).toContain('counts_by_bot')
    })
})
