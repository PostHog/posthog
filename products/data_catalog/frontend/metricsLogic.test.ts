import { router } from 'kea-router'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    dataCatalogMetricsApproveCreate,
    dataCatalogMetricsBulkApproveCreate,
    dataCatalogMetricsBulkDeleteCreate,
    dataCatalogMetricsCreate,
    dataCatalogMetricsDestroy,
    dataCatalogMetricsList,
} from './generated/api'
import type { DataCatalogMetricApi } from './generated/api.schemas'
import { metricsLogic } from './metricsLogic'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        detail: string | null
        constructor(message?: string, status?: number, _headers?: unknown, data?: { detail?: string }) {
            super(message)
            this.status = status
            this.detail = data?.detail ?? null
        }
    }
    return {
        __esModule: true,
        default: { insights: { list: jest.fn().mockResolvedValue({ results: [] }) } },
        ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
        ApiError,
    }
})

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('./generated/api', () => ({
    dataCatalogMetricsList: jest.fn(),
    dataCatalogMetricsCreate: jest.fn(),
    dataCatalogMetricsApproveCreate: jest.fn(),
    dataCatalogMetricsRefreshFromInsightCreate: jest.fn(),
    dataCatalogMetricsDestroy: jest.fn(),
    dataCatalogMetricsBulkApproveCreate: jest.fn(),
    dataCatalogMetricsBulkDeleteCreate: jest.fn(),
}))

function buildMetric(overrides: Partial<DataCatalogMetricApi> = {}): DataCatalogMetricApi {
    return {
        id: 'metric-1',
        name: 'weekly_active_users',
        description: 'Weekly active users',
        definition_kind: 'HogQLQuery',
        status: 'proposed',
        is_drifted: false,
        owner: null,
        ...overrides,
    } as DataCatalogMetricApi
}

const BULK_ACTIONS = [
    ['approve', dataCatalogMetricsBulkApproveCreate, 'bulkApproveMetrics'],
    ['delete', dataCatalogMetricsBulkDeleteCreate, 'bulkDeleteMetrics'],
] as const

describe('metricsLogic', () => {
    let logic: ReturnType<typeof metricsLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        ;(dataCatalogMetricsList as jest.Mock).mockResolvedValue({ results: [buildMetric()] })
        initKeaTests()
        logic = metricsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMetricsSuccess'])
    })

    it('replaces the row with the response when approve succeeds', async () => {
        ;(dataCatalogMetricsApproveCreate as jest.Mock).mockResolvedValue(buildMetric({ status: 'approved' }))

        logic.actions.approveMetric('weekly_active_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics[0].status).toEqual('approved')
    })

    it('leaves the row untouched and surfaces refresh when approve returns 409', async () => {
        ;(dataCatalogMetricsApproveCreate as jest.Mock).mockRejectedValue(new ApiError('drifted', 409))

        logic.actions.approveMetric('weekly_active_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics[0].status).toEqual('proposed')
        const errorCall = (lemonToast.error as jest.Mock).mock.calls.at(-1)
        expect(errorCall?.[1]?.button?.label).toEqual('Refresh from insight')
    })

    it('guards double-submit and closes the modal when create succeeds', async () => {
        let resolveCreate: (metric: DataCatalogMetricApi) => void = () => {}
        ;(dataCatalogMetricsCreate as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolveCreate = resolve
            })
        )

        logic.actions.openNewMetricModal()
        logic.actions.setNewMetricForm({
            name: 'monthly_active_users',
            description: 'Monthly active users',
            definitionType: 'insight',
            sourceInsightShortId: 'abc123',
        })

        logic.actions.createMetric()
        logic.actions.createMetric()
        expect(dataCatalogMetricsCreate).toHaveBeenCalledTimes(1)

        resolveCreate(buildMetric({ id: 'metric-2', name: 'monthly_active_users' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.newMetricModalOpen).toEqual(false)
        expect(logic.values.allMetrics.map((metric) => metric.name)).toContain('monthly_active_users')
    })

    it('creates a markdown metric as a stub and routes to the metric page to author it', async () => {
        ;(dataCatalogMetricsCreate as jest.Mock).mockResolvedValue(
            buildMetric({ id: 'metric-4', name: 'mrr', definition_kind: null })
        )

        logic.actions.openNewMetricModal()
        logic.actions.setNewMetricForm({
            name: 'mrr',
            description: 'Monthly recurring revenue',
            definitionType: 'markdown',
        })
        logic.actions.createMetric()
        await expectLogic(logic).toFinishAllListeners()

        const body = (dataCatalogMetricsCreate as jest.Mock).mock.calls.at(-1)?.[1]
        expect(body.definition).toBeUndefined()
        expect(router.values.location.pathname).toContain(urls.dataCatalogMetric('mrr'))
        expect(router.values.searchParams.edit).toEqual('definition')
    })

    it('does not create a SQL metric from the modal', async () => {
        logic.actions.openNewMetricModal()
        logic.actions.setNewMetricForm({
            name: 'sql_metric',
            description: 'Defined in the SQL editor',
            definitionType: 'sql',
        })

        logic.actions.createMetric()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsCreate).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith('Create SQL metrics from the SQL editor.')
        expect(logic.values.newMetricModalOpen).toEqual(true)
    })

    it.each([
        [
            'carries the typed values into the SQL editor URL',
            {
                name: 'monthly_active_users',
                display_name: 'Monthly active users',
                description: 'Unique users seen in the last 30 days',
                unit: 'users',
            },
            {
                name: 'monthly_active_users',
                display_name: 'Monthly active users',
                description: 'Unique users seen in the last 30 days',
                unit: 'users',
            },
        ],
        ['omits the prefill from the SQL editor URL when nothing was typed', {}, undefined],
    ])('%s', async (_case, formValues, expectedPrefill) => {
        logic.actions.openNewMetricModal()
        logic.actions.setNewMetricForm(formValues)

        logic.actions.openSqlEditorForNewMetric()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.newMetricModalOpen).toEqual(false)
        expect(router.values.location.pathname).toContain(urls.sqlEditor())
        expect(router.values.searchParams.source).toEqual('metric')
        expect(router.values.searchParams.metric_prefill).toEqual(expectedPrefill)
    })

    it('removes the row when delete succeeds', async () => {
        ;(dataCatalogMetricsDestroy as jest.Mock).mockResolvedValue(undefined)

        logic.actions.deleteMetric('weekly_active_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics).toHaveLength(0)
    })

    it('loads every page of metrics', async () => {
        ;(dataCatalogMetricsList as jest.Mock)
            .mockResolvedValueOnce({
                results: [buildMetric({ id: 'metric-1', name: 'first' })],
                next: 'http://localhost/api/projects/1/data_catalog/metrics/?limit=100&offset=100',
            })
            .mockResolvedValueOnce({ results: [buildMetric({ id: 'metric-2', name: 'second' })], next: null })

        logic.actions.loadMetrics()
        await expectLogic(logic).toDispatchActions(['loadMetricsSuccess'])

        expect(logic.values.allMetrics.map((metric) => metric.name)).toEqual(['first', 'second'])
        expect((dataCatalogMetricsList as jest.Mock).mock.calls.map((call) => call[1].offset)).toEqual([0, 0, 100])
    })

    it('patches approved rows and reloads to reconcile skipped ones', async () => {
        logic.actions.loadMetricsSuccess([
            buildMetric({ id: 'metric-1', name: 'first' }),
            buildMetric({ id: 'metric-2', name: 'second' }),
        ])
        ;(dataCatalogMetricsBulkApproveCreate as jest.Mock).mockResolvedValue({
            approved: [buildMetric({ id: 'metric-1', name: 'first', status: 'approved' })],
            skipped: [{ name: 'second', reason: 'Drifted from its source insight' }],
        })
        // The skip means the page's copy of 'second' is stale, so the reload returns the server's
        // current state, where 'second' is now drifted.
        ;(dataCatalogMetricsList as jest.Mock).mockResolvedValue({
            results: [
                buildMetric({ id: 'metric-1', name: 'first', status: 'approved' }),
                buildMetric({ id: 'metric-2', name: 'second', is_drifted: true }),
            ],
            next: null,
        })
        const listCallsBefore = (dataCatalogMetricsList as jest.Mock).mock.calls.length
        const onSuccess = jest.fn()

        logic.actions.bulkApproveMetrics(['first', 'second'], onSuccess)
        await expectLogic(logic).toFinishAllListeners()

        expect((dataCatalogMetricsList as jest.Mock).mock.calls.length).toBeGreaterThan(listCallsBefore)
        expect(logic.values.allMetrics.map((metric) => [metric.name, metric.is_drifted])).toEqual([
            ['first', false],
            ['second', true],
        ])
        expect(onSuccess).toHaveBeenCalled()
        expect(lemonToast.warning).toHaveBeenCalledWith('Skipped 1 metric: Drifted from its source insight (1)')
        expect(logic.values.bulkActionInFlight).toBeNull()
    })

    it('removes the deleted rows and clears the selection', async () => {
        logic.actions.loadMetricsSuccess([
            buildMetric({ id: 'metric-1', name: 'first' }),
            buildMetric({ id: 'metric-2', name: 'second' }),
        ])
        ;(dataCatalogMetricsBulkDeleteCreate as jest.Mock).mockResolvedValue({ deleted: ['first'], skipped: [] })
        const onSuccess = jest.fn()

        logic.actions.bulkDeleteMetrics(['first'], onSuccess)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics.map((metric) => metric.name)).toEqual(['second'])
        expect(onSuccess).toHaveBeenCalled()
    })

    it('reloads to drop skipped rows after bulk delete', async () => {
        logic.actions.loadMetricsSuccess([
            buildMetric({ id: 'metric-1', name: 'first' }),
            buildMetric({ id: 'metric-2', name: 'second' }),
        ])
        ;(dataCatalogMetricsBulkDeleteCreate as jest.Mock).mockResolvedValue({
            deleted: ['first'],
            skipped: [{ name: 'second', reason: 'Not found' }],
        })
        // 'second' was skipped as already gone, so the reload returns the server's current list
        // without it and the stale row leaves the table.
        ;(dataCatalogMetricsList as jest.Mock).mockResolvedValue({ results: [], next: null })
        const onSuccess = jest.fn()

        logic.actions.bulkDeleteMetrics(['first', 'second'], onSuccess)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics).toHaveLength(0)
        expect(onSuccess).toHaveBeenCalled()
        expect(lemonToast.warning).toHaveBeenCalledWith('Skipped 1 metric: Not found (1)')
    })

    it.each(BULK_ACTIONS)('keeps the selection when bulk %s fails', async (_label, client, actionName) => {
        ;(client as jest.Mock).mockRejectedValue(new ApiError('nope', 500))
        const onSuccess = jest.fn()

        logic.actions[actionName](['weekly_active_users'], onSuccess)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics).toHaveLength(1)
        expect(onSuccess).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.bulkActionInFlight).toBeNull()
    })

    it.each(BULK_ACTIONS)('ignores a second bulk %s while one is in flight', async (_label, client, actionName) => {
        let resolveRequest: (response: unknown) => void = () => {}
        ;(client as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            })
        )

        logic.actions[actionName](['weekly_active_users'])
        logic.actions[actionName](['weekly_active_users'])
        expect(client).toHaveBeenCalledTimes(1)

        resolveRequest({ approved: [], deleted: [], skipped: [] })
        await expectLogic(logic).toFinishAllListeners()
    })

    it('does not fire a bulk request while a row action on one of its metrics runs', async () => {
        logic.actions.setActionInFlight('weekly_active_users', true)

        logic.actions.bulkApproveMetrics(['weekly_active_users'])
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsBulkApproveCreate).not.toHaveBeenCalled()
    })

    it('does not fire a row action while a bulk action runs', async () => {
        logic.actions.setBulkActionInFlight('approve')

        logic.actions.approveMetric('weekly_active_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsApproveCreate).not.toHaveBeenCalled()
    })

    it('creates a metric from an insight with the short id and no definition', async () => {
        ;(dataCatalogMetricsCreate as jest.Mock).mockResolvedValue(
            buildMetric({ id: 'metric-3', name: 'from_insight', source_insight_short_id: 'abc123' })
        )

        logic.actions.openMetricFromInsightModal()
        logic.actions.createMetricFromInsight({
            name: 'from_insight',
            display_name: '',
            description: 'Snapshotted from an insight',
            source_insight_short_id: 'abc123',
        })
        await expectLogic(logic).toFinishAllListeners()

        const body = (dataCatalogMetricsCreate as jest.Mock).mock.calls.at(-1)?.[1]
        expect(body.source_insight_short_id).toEqual('abc123')
        expect(body.definition).toBeUndefined()
        expect(logic.values.metricFromInsightModalOpen).toEqual(false)
        expect(logic.values.allMetrics.map((metric) => metric.name)).toContain('from_insight')
    })
})
