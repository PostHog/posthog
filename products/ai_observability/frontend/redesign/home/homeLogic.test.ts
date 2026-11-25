import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TraceMetricKeyApi } from '../../generated/api.schemas'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { METRICS, METRICS_NOT_SET_UP, RANGE_TOO_LONG_DETAIL } from './homeFixtures'
import { homeLogic } from './homeLogic'

const METRICS_URL = '/api/projects/:team_id/ai_observability/traces/metrics/'

type Answer = [number, unknown]

describe('homeLogic', () => {
    let requests: Record<string, string>[] = []
    let metricsAnswer: Answer
    let dashboards: { id: number }[]
    let logic: ReturnType<typeof homeLogic.build>

    async function mount(): Promise<void> {
        logic = homeLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        requests = []
        metricsAnswer = [200, METRICS]
        dashboards = [{ id: 42 }]
        useMocks({
            get: {
                '/api/projects/:team_id/dashboards/': () => [200, { count: dashboards.length, results: dashboards }],
                [METRICS_URL]: ({ request }) => {
                    requests.push(Object.fromEntries(new URL(request.url).searchParams))
                    return metricsAnswer
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.aiObservabilityDashboard())
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('loads metrics with the shell range and switch', async () => {
        await mount()

        expect(requests).toEqual([{ date_from: '-7d', filter_test_accounts: 'false' }])
        expect(logic.values).toMatchObject({ metrics: METRICS, metricsFailure: null })
        expect(posthog.capture).toHaveBeenCalledWith('llma home metrics loaded', {
            load_ms: expect.any(Number),
            date_from: '-7d',
            date_to: null,
            filter_test_accounts: false,
        })
    })

    it.each([
        ['the range', () => shellScopeLogic.actions.setDateRange('-24h', null), { date_from: '-24h' }],
        ['the switch', () => shellScopeLogic.actions.setFilterTestAccounts(true), { filter_test_accounts: 'true' }],
    ])('reloads when %s changes', async (_name, change, expected) => {
        await mount()

        change()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests).toHaveLength(2)
        expect(requests[1]).toMatchObject(expected)
    })

    it('keeps the detail of a range_too_long 422 and clears it on the next read', async () => {
        silenceKeaLoadersErrors()
        metricsAnswer = [422, { detail: RANGE_TOO_LONG_DETAIL, code: 'range_too_long' }]
        await mount()

        expect(logic.values).toMatchObject({
            metrics: null,
            metricsFailure: { kind: 'range_too_long', detail: RANGE_TOO_LONG_DETAIL },
        })

        metricsAnswer = [200, METRICS]
        shellScopeLogic.actions.setDateRange('-24h', null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({ metrics: METRICS, metricsFailure: null })
    })

    it('drops the tiles of the previous range when the next read fails', async () => {
        silenceKeaLoadersErrors()
        await mount()

        metricsAnswer = [500, { detail: 'boom' }]
        shellScopeLogic.actions.setDateRange('-24h', null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({ metrics: null, metricsFailure: { kind: 'error' } })
    })

    it('reports any other failure as an error', async () => {
        silenceKeaLoadersErrors()
        metricsAnswer = [500, { detail: 'boom' }]
        await mount()

        expect(logic.values).toMatchObject({ metrics: null, metricsFailure: { kind: 'error' } })
        expect(posthog.capture).not.toHaveBeenCalledWith('llma home metrics loaded', expect.anything())
    })

    it('loads the id of the existing dashboard', async () => {
        await mount()

        expect(logic.values.dashboardId).toBe(42)
    })

    it('links the traces, errors and sessions tiles to their lists with the range', async () => {
        await mount()
        shellScopeLogic.actions.setDateRange('-24h', null)

        expect(logic.values.tileLinks).toEqual({
            [TraceMetricKeyApi.Traces]: '/ai-observability/traces?date_from=-24h&filter_test_accounts=false',
            [TraceMetricKeyApi.Sessions]: '/ai-observability/sessions?date_from=-24h&filter_test_accounts=false',
            [TraceMetricKeyApi.ErrorRate]:
                '/ai-observability/traces?date_from=-24h&filter_test_accounts=false&view=errors',
        })
    })

    it('opens one chart at a time and links it to an SQL insight of its own query', async () => {
        await mount()
        const errorRate = METRICS.tiles.find((tile) => tile.key === TraceMetricKeyApi.ErrorRate)

        logic.actions.toggleChart(TraceMetricKeyApi.Cost)
        logic.actions.toggleChart(TraceMetricKeyApi.ErrorRate)
        expect(logic.values.openChart).toEqual(errorRate)
        const opened = new URL(logic.values.openChartInsightUrl ?? '', 'http://localhost').searchParams.get(
            'open_query'
        )
        expect(JSON.parse(opened ?? '{}')).toMatchObject({ source: { query: errorRate?.insightQuery } })

        logic.actions.toggleChart(TraceMetricKeyApi.ErrorRate)
        expect(logic.values.openChart).toBeNull()

        logic.actions.toggleChart(TraceMetricKeyApi.Cost)
        logic.actions.closeChart()
        expect(logic.values).toMatchObject({ openChart: null, openChartInsightUrl: null })
    })

    it('opens no chart for a tile that is not set up', async () => {
        metricsAnswer = [200, METRICS_NOT_SET_UP]
        await mount()

        logic.actions.toggleChart(TraceMetricKeyApi.Sessions)

        expect(logic.values.openChart).toBeNull()
    })
})
