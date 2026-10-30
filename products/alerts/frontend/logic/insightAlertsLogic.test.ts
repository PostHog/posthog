import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { insightsApi } from 'scenes/insights/utils/api'

import { Node, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, HogFunctionType, InsightLogicProps, InsightModel, InsightShortId } from '~/types'

import type { AlertType } from '../types'
import {
    alertsUnsupportedReason,
    areAlertsSupportedForInsight,
    areAnomalyAlertsSupportedForInsight,
    insightAlertsLogic,
} from './insightAlertsLogic'

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

// Metrics insights persist their query as a bare MetricsQuery node — no InsightVizNode wrapper.
const METRICS_QUERY = {
    kind: NodeKind.MetricsQuery,
    clauses: [{ name: 'a', metricName: 'queue.depth', aggregation: 'avg' }],
}

const funnelWithViz = (funnelVizType?: string): Node & { source: Record<string, any> } => ({
    ...FUNNEL_QUERY,
    source: { ...FUNNEL_QUERY.source, funnelsFilter: { funnelVizType } },
})

const SQL_QUERY = {
    kind: NodeKind.DataVisualizationNode,
    source: { kind: NodeKind.HogQLQuery, query: 'SELECT count() FROM events' },
}

const RETENTION_QUERY = {
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.RetentionQuery, retentionFilter: {} },
}

describe('insightAlertsLogic', () => {
    let listSpy: jest.SpyInstance
    let hogFunctionsListSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        listSpy = jest.spyOn(api.alerts, 'list').mockResolvedValue({ results: [], count: 0 })
        hogFunctionsListSpy = jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [], count: 0 })
    })

    afterEach(() => {
        listSpy.mockRestore()
        hogFunctionsListSpy.mockRestore()
    })

    function mountInsightStack(insightLogicProps: InsightLogicProps): void {
        insightLogic(insightLogicProps).mount()
        insightDataLogic(insightLogicProps).mount()
        insightVizDataLogic(insightLogicProps).mount()
    }

    it('hydrates inline insight.alerts on a deferred mount without alerts or destination-count requests', async () => {
        const inlineAlerts = [{ id: 'alert-a', name: 'Inline' }] as AlertType[]
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: {
                ...createEmptyInsight(Insight42),
                id: 42,
                query: API_QUERY,
                alerts: inlineAlerts,
            },
        }
        mountInsightStack(insightLogicProps)

        const alertsLogic = insightAlertsLogic({
            insightId: 42,
            insightLogicProps,
            deferInitialAlertsLoad: true,
        })
        alertsLogic.mount()

        await expectLogic(alertsLogic).toFinishAllListeners().toMatchValues({ alerts: inlineAlerts })
        expect(listSpy).not.toHaveBeenCalled()
        expect(hogFunctionsListSpy).not.toHaveBeenCalled()
    })

    it('reloads alerts after the insight saves', async () => {
        const updateSpy = jest
            .spyOn(insightsApi, 'update')
            .mockResolvedValue({ ...createEmptyInsight(Insight42), id: 42 } as InsightModel)
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: {
                ...createEmptyInsight(Insight42),
                id: 42,
                query: API_QUERY,
                alerts: [{ id: 'alert-a', name: 'Inline' }] as AlertType[],
            },
        }
        mountInsightStack(insightLogicProps)
        const alertsLogic = insightAlertsLogic({ insightId: 42, insightLogicProps, deferInitialAlertsLoad: true })
        alertsLogic.mount()

        insightLogic(insightLogicProps).actions.saveInsight()

        await expectLogic(alertsLogic).toDispatchActions(['loadAlerts', 'loadAlertsSuccess'])
        expect(listSpy).toHaveBeenCalled()
        updateSpy.mockRestore()
    })

    it('does not fetch on a deferred mount when the cached insight has no alerts field', async () => {
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

    it('loads destination counts for all alerts in one request', async () => {
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: { ...createEmptyInsight(Insight42), id: 42, query: API_QUERY, alerts: [] },
        }
        mountInsightStack(insightLogicProps)
        hogFunctionsListSpy.mockResolvedValue({
            count: 3,
            results: [
                { filters: { properties: [{ key: 'alert_id', value: 'alert-a' }] } },
                { filters: { properties: [{ key: 'alert_id', value: 'alert-a' }] } },
                { filters: { properties: [{ key: 'alert_id', value: 'alert-b' }] } },
            ] as HogFunctionType[],
        })
        const alertsLogic = insightAlertsLogic({ insightId: 42, insightLogicProps, deferInitialAlertsLoad: true })
        alertsLogic.mount()
        const alerts = [{ id: 'alert-a' }, { id: 'alert-b' }] as AlertType[]

        await expectLogic(alertsLogic, () => alertsLogic.actions.loadAlertsSuccess(alerts))
            .toFinishAllListeners()
            .toMatchValues({ alertDestinationCounts: { 'alert-a': 2, 'alert-b': 1 } })

        expect(hogFunctionsListSpy).toHaveBeenCalledTimes(1)
    })

    it.each([
        { name: 'metrics', query: METRICS_QUERY, metricsEnabled: true, expectedWarning: false },
        { name: 'metrics', query: METRICS_QUERY, metricsEnabled: false, expectedWarning: false },
        { name: 'flow funnel', query: funnelWithViz('flow'), metricsEnabled: false, expectedWarning: false },
        { name: 'SQL', query: SQL_QUERY, metricsEnabled: false, expectedWarning: false },
        { name: 'retention', query: RETENTION_QUERY, metricsEnabled: true, expectedWarning: true },
    ])(
        'with metrics flag $metricsEnabled, a $name query on an insight with alerts sets the deletion warning to $expectedWarning',
        async ({ query, metricsEnabled, expectedWarning }) => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.METRICS]: metricsEnabled })
            const insightLogicProps: InsightLogicProps = {
                dashboardItemId: Insight42,
                cachedInsight: {
                    ...createEmptyInsight(Insight42),
                    id: 42,
                    query,
                    alerts: [{ id: 'alert-a' }] as AlertType[],
                },
            }
            mountInsightStack(insightLogicProps)
            const alertsLogic = insightAlertsLogic({ insightId: 42, insightLogicProps, deferInitialAlertsLoad: true })
            alertsLogic.mount()

            await expectLogic(alertsLogic, () => {
                insightVizDataLogic(insightLogicProps).actions.setQuery(query)
            }).toDispatchActions(['setShouldShowAlertDeletionWarning'])
            expect(alertsLogic.values.shouldShowAlertDeletionWarning).toBe(expectedWarning)
        }
    )

    it('refreshes destination counts after an alert is saved', async () => {
        const insightLogicProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            dashboardId: 1,
            cachedInsight: { ...createEmptyInsight(Insight42), id: 42, query: API_QUERY, alerts: [] },
        }
        mountInsightStack(insightLogicProps)
        hogFunctionsListSpy.mockResolvedValue({
            count: 1,
            results: [{ filters: { properties: [{ key: 'alert_id', value: 'alert-a' }] } }] as HogFunctionType[],
        })
        const alertsLogic = insightAlertsLogic({ insightId: 42, insightLogicProps, deferInitialAlertsLoad: true })
        alertsLogic.mount()

        await expectLogic(alertsLogic, () => alertsLogic.actions.upsertAlert({ id: 'alert-a' } as AlertType))
            .toFinishAllListeners()
            .toMatchValues({ alertDestinationCounts: { 'alert-a': 1 } })

        expect(hogFunctionsListSpy).toHaveBeenCalledTimes(1)
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

    it('supports funnel insight viz by default', () => {
        expect(areAlertsSupportedForInsight(FUNNEL_QUERY)).toBe(true)
    })

    it('supports bare metrics query nodes only when metricsAlertsEnabled', () => {
        expect(areAlertsSupportedForInsight(METRICS_QUERY, { metricsAlertsEnabled: true })).toBe(true)
        expect(areAlertsSupportedForInsight(METRICS_QUERY)).toBe(false)
    })

    it('supports steps and trends funnels but not time-to-convert or flow', () => {
        expect(areAlertsSupportedForInsight(funnelWithViz('steps'))).toBe(true)
        expect(areAlertsSupportedForInsight(funnelWithViz('trends'))).toBe(true)
        expect(areAlertsSupportedForInsight(funnelWithViz('time_to_convert'))).toBe(false)
        expect(areAlertsSupportedForInsight(funnelWithViz('flow'))).toBe(false)
    })

    const trendsWithDisplay = (display?: ChartDisplayType): Record<string, any> => ({
        ...API_QUERY,
        source: { ...API_QUERY.source, trendsFilter: display ? { display } : null },
    })

    it.each<[string, Record<string, any>, boolean]>([
        ['line graph trends', trendsWithDisplay(ChartDisplayType.ActionsLineGraph), true],
        ['default display trends', trendsWithDisplay(), true],
        ['bold number trends', trendsWithDisplay(ChartDisplayType.BoldNumber), false],
        ['bar value trends', trendsWithDisplay(ChartDisplayType.ActionsBarValue), false],
        ['SQL', SQL_QUERY, true],
        ['funnel', FUNNEL_QUERY, false],
        ['metrics', METRICS_QUERY, false],
    ])('reports anomaly support for %s with the metrics flag on', (_name, query, expected) => {
        expect(areAnomalyAlertsSupportedForInsight(query, { metricsAlertsEnabled: true })).toBe(expected)
    })
})

describe('alertsUnsupportedReason', () => {
    it.each([
        ['metrics gated off', {}, ['trends', 'SQL', 'funnel'], ['metrics']],
        ['metrics enabled', { metricsAlertsEnabled: true }, ['trends', 'SQL', 'funnel', 'metrics'], []],
    ])('always lists trends/SQL/funnel and gates only metrics: %s', (_name, options, included, excluded) => {
        const reason = alertsUnsupportedReason(options)
        expect(included.every((type) => reason.includes(type))).toBe(true)
        expect(excluded.every((type) => !reason.includes(type))).toBe(true)
    })

    // A time-to-convert/flow funnel is itself a funnel, so the generic "funnel insights are supported"
    // copy reads as a contradiction; the reason should name the real cause instead.
    it('gives a funnel-viz-specific reason for time-to-convert / flow funnels', () => {
        for (const viz of ['time_to_convert', 'flow']) {
            const reason = alertsUnsupportedReason({}, funnelWithViz(viz))
            expect(reason).toContain('conversion rate')
            expect(reason).toContain('steps or trends')
            expect(reason).not.toContain('only available for')
        }
        // No query → backward-compatible generic copy.
        expect(alertsUnsupportedReason({})).toContain('only available for')
    })
})
