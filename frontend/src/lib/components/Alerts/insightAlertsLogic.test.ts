import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId } from '~/types'

import { alertsUnsupportedReason, areAlertsSupportedForInsight, insightAlertsLogic } from './insightAlertsLogic'
import type { AlertType } from './types'

const Insight42 = '42' as InsightShortId

const API_QUERY = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: 'total' }],
        trendsFilter: { display: 'ActionsLineGraph' },
    },
}

const FUNNEL_QUERY = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.FunnelsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
    },
}

describe('insightAlertsLogic', () => {
    let listSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        listSpy = jest.spyOn(api.alerts, 'list').mockResolvedValue({ results: [], count: 0 })
    })

    afterEach(() => {
        listSpy.mockRestore()
    })

    function mountInsightStack(insightLogicProps: InsightLogicProps): void {
        insightLogic(insightLogicProps).mount()
        insightDataLogic(insightLogicProps).mount()
        insightVizDataLogic(insightLogicProps).mount()
    }

    it('does not hydrate from empty insight.alerts or fetch on mount when deferInitialAlertsLoad is true', async () => {
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: {
                ...createEmptyInsight(Insight42),
                id: 42,
                query: API_QUERY,
                alerts: [],
            },
        }
        mountInsightStack(insightLogicProps)

        const alertsLogic = insightAlertsLogic({
            insightId: 42,
            insightLogicProps,
            deferInitialAlertsLoad: true,
        })
        alertsLogic.mount()

        await expectLogic(alertsLogic).toMatchValues({ alerts: [] })
        await expectLogic(alertsLogic).toNotHaveDispatchedActions(['loadAlerts', 'loadAlertsSuccess'])
        expect(listSpy).not.toHaveBeenCalled()
    })

    it('calls the alerts API when loadAlerts runs after a deferred mount', async () => {
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: {
                ...createEmptyInsight(Insight42),
                id: 42,
                query: API_QUERY,
                alerts: [],
            },
        }
        mountInsightStack(insightLogicProps)

        const alertsLogic = insightAlertsLogic({
            insightId: 42,
            insightLogicProps,
            deferInitialAlertsLoad: true,
        })
        alertsLogic.mount()

        await expectLogic(alertsLogic, () => {
            alertsLogic.actions.loadAlerts()
        }).toFinishAllListeners()

        expect(listSpy).toHaveBeenCalledWith(42)
    })

    it('dispatches loadAlerts on mount when not deferred and cached insight has no alerts field', async () => {
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: {
                ...createEmptyInsight(Insight42),
                id: 42,
                query: API_QUERY,
            },
        }
        mountInsightStack(insightLogicProps)

        const alertsLogic = insightAlertsLogic({
            insightId: 42,
            insightLogicProps,
        })
        alertsLogic.mount()

        await expectLogic(alertsLogic).toFinishAllListeners()
        expect(listSpy).toHaveBeenCalledWith(42)
    })

    it('uses loadAlertsSuccess from insight.alerts on mount when not deferred and does not call the API for an empty array', async () => {
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: {
                ...createEmptyInsight(Insight42),
                id: 42,
                query: API_QUERY,
                alerts: [],
            },
        }
        mountInsightStack(insightLogicProps)

        const alertsLogic = insightAlertsLogic({
            insightId: 42,
            insightLogicProps,
        })
        alertsLogic.mount()

        await expectLogic(alertsLogic).toDispatchActions(['loadAlertsSuccess'])
        await expectLogic(alertsLogic).toMatchValues({ alerts: [] })
        expect(listSpy).not.toHaveBeenCalled()
    })

    it('upsertAlert appends then replaces by id', async () => {
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: {
                ...createEmptyInsight(Insight42),
                id: 42,
                query: API_QUERY,
                alerts: [],
            },
        }
        mountInsightStack(insightLogicProps)

        const alertsLogic = insightAlertsLogic({
            insightId: 42,
            insightLogicProps,
            deferInitialAlertsLoad: true,
        })
        alertsLogic.mount()

        const first = { id: 'alert-a', name: 'First' } as AlertType
        const updated = { id: 'alert-a', name: 'Updated' } as AlertType

        await expectLogic(alertsLogic, () => {
            alertsLogic.actions.upsertAlert(first)
            alertsLogic.actions.upsertAlert({ id: 'alert-b', name: 'Other' } as AlertType)
            alertsLogic.actions.upsertAlert(updated)
        }).toMatchValues({
            alerts: [updated, expect.objectContaining({ id: 'alert-b', name: 'Other' })],
        })
    })

    it('removeAlert drops the matching alert id', async () => {
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: {
                ...createEmptyInsight(Insight42),
                id: 42,
                query: API_QUERY,
                alerts: [],
            },
        }
        mountInsightStack(insightLogicProps)

        const alertsLogic = insightAlertsLogic({
            insightId: 42,
            insightLogicProps,
            deferInitialAlertsLoad: true,
        })
        alertsLogic.mount()

        await expectLogic(alertsLogic, () => {
            alertsLogic.actions.upsertAlert({ id: 'keep', name: 'K' } as AlertType)
            alertsLogic.actions.upsertAlert({ id: 'drop', name: 'D' } as AlertType)
            alertsLogic.actions.removeAlert('drop')
        }).toMatchValues({
            alerts: [expect.objectContaining({ id: 'keep' })],
        })
    })
})

describe('areAlertsSupportedForInsight', () => {
    it('returns false when query is null or undefined', () => {
        expect(areAlertsSupportedForInsight(null)).toBe(false)
        expect(areAlertsSupportedForInsight(undefined)).toBe(false)
    })

    it.each([
        ['with trendsFilter', API_QUERY],
        [
            'without trendsFilter',
            {
                ...API_QUERY,
                source: {
                    ...API_QUERY.source,
                    trendsFilter: undefined,
                },
            },
        ],
        [
            'with null trendsFilter',
            {
                ...API_QUERY,
                source: {
                    ...API_QUERY.source,
                    trendsFilter: null,
                },
            },
        ],
    ])('returns true for trends insight viz %s', (_name, query) => {
        expect(areAlertsSupportedForInsight(query)).toBe(true)
    })

    it('returns false for funnel insight viz when the funnel flag is off', () => {
        expect(areAlertsSupportedForInsight(FUNNEL_QUERY)).toBe(false)
    })

    it('returns true for funnel insight viz when funnelAlertsEnabled', () => {
        expect(areAlertsSupportedForInsight(FUNNEL_QUERY, { funnelAlertsEnabled: true })).toBe(true)
    })

    it('supports steps and trends funnels but not time-to-convert or flow', () => {
        const withViz = (funnelVizType?: string): Record<string, any> => ({
            ...FUNNEL_QUERY,
            source: { ...FUNNEL_QUERY.source, funnelsFilter: { funnelVizType } },
        })
        const opts = { funnelAlertsEnabled: true }
        expect(areAlertsSupportedForInsight(withViz('steps'), opts)).toBe(true)
        expect(areAlertsSupportedForInsight(withViz('trends'), opts)).toBe(true)
        expect(areAlertsSupportedForInsight(withViz('time_to_convert'), opts)).toBe(false)
        expect(areAlertsSupportedForInsight(withViz('flow'), opts)).toBe(false)
    })
})

describe('alertsUnsupportedReason', () => {
    it.each([
        ['only trends (no flags)', {}, ['trends'], ['SQL', 'funnel']],
        ['trends + SQL', { hogqlAlertsEnabled: true }, ['trends', 'SQL'], ['funnel']],
        ['trends + funnel', { funnelAlertsEnabled: true }, ['trends', 'funnel'], ['SQL']],
        ['all three', { hogqlAlertsEnabled: true, funnelAlertsEnabled: true }, ['trends', 'SQL', 'funnel'], []],
    ])('lists only enabled types: %s', (_name, options, included, excluded) => {
        const reason = alertsUnsupportedReason(options)
        expect(included.every((type) => reason.includes(type))).toBe(true)
        expect(excluded.every((type) => !reason.includes(type))).toBe(true)
    })

    // A time-to-convert/flow funnel is itself a funnel, so the generic "funnel insights are supported"
    // copy reads as a contradiction; the reason should name the real cause instead.
    it('gives a funnel-viz-specific reason for time-to-convert / flow funnels', () => {
        const funnelWithViz = (funnelVizType: string): Record<string, any> => ({
            ...FUNNEL_QUERY,
            source: { ...FUNNEL_QUERY.source, funnelsFilter: { funnelVizType } },
        })
        const options = { funnelAlertsEnabled: true }
        for (const viz of ['time_to_convert', 'flow']) {
            const reason = alertsUnsupportedReason(options, funnelWithViz(viz))
            expect(reason).toContain('conversion rate')
            expect(reason).toContain('steps or trends')
            expect(reason).not.toContain('only available for')
        }
        // No query → backward-compatible generic copy.
        expect(alertsUnsupportedReason(options)).toContain('only available for')
    })
})
