import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    dataCatalogMetricsApproveCreate,
    dataCatalogMetricsBulkApproveCreate,
    dataCatalogMetricsBulkChangeOwnerCreate,
    dataCatalogMetricsBulkDeleteCreate,
    dataCatalogMetricsCreate,
    dataCatalogMetricsDestroy,
    dataCatalogMetricsList,
    dataCatalogMetricsPartialUpdate,
} from './generated/api'
import type { DataCatalogMetricApi } from './generated/api.schemas'
import { metricsLogic } from './metricsLogic'
import { openOverwriteMetricDialog } from './openOverwriteMetricDialog'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        detail: string | null
        code: string | null
        data?: Record<string, any>
        constructor(
            message?: string,
            status?: number,
            _headers?: unknown,
            data?: { detail?: string; code?: string } & Record<string, any>
        ) {
            super(message)
            this.status = status
            this.detail = data?.detail ?? null
            this.code = data?.code ?? null
            this.data = data
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

jest.mock('./openOverwriteMetricDialog', () => ({ openOverwriteMetricDialog: jest.fn() }))

jest.mock('./generated/api', () => ({
    dataCatalogMetricsList: jest.fn(),
    dataCatalogMetricsCreate: jest.fn(),
    dataCatalogMetricsApproveCreate: jest.fn(),
    dataCatalogMetricsRefreshFromInsightCreate: jest.fn(),
    dataCatalogMetricsDestroy: jest.fn(),
    dataCatalogMetricsBulkApproveCreate: jest.fn(),
    dataCatalogMetricsBulkDeleteCreate: jest.fn(),
    dataCatalogMetricsBulkChangeOwnerCreate: jest.fn(),
    dataCatalogMetricsPartialUpdate: jest.fn(),
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
        expect(dataCatalogMetricsList).not.toHaveBeenCalled()
        void logic.values.allMetrics
        await expectLogic(logic).toDispatchActions(['loadMetricsSuccess'])
    })

    it('replaces the row with the response when approve succeeds', async () => {
        ;(dataCatalogMetricsApproveCreate as jest.Mock).mockResolvedValue(buildMetric({ status: 'approved' }))

        logic.actions.approveMetric('weekly_active_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics[0].status).toEqual('approved')
    })

    it('saves the new owner and replaces the row with the response', async () => {
        ;(dataCatalogMetricsPartialUpdate as jest.Mock).mockResolvedValue(
            buildMetric({ owner: 'rose.dawson@posthog.com' })
        )

        logic.actions.setMetricOwner('weekly_active_users', 'rose.dawson@posthog.com')
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsPartialUpdate).toHaveBeenCalledWith('1', 'weekly_active_users', {
            owner: 'rose.dawson@posthog.com',
        })
        expect(logic.values.allMetrics[0].owner).toEqual('rose.dawson@posthog.com')
    })

    it('leaves the row untouched and surfaces refresh when approve returns 409', async () => {
        ;(dataCatalogMetricsApproveCreate as jest.Mock).mockRejectedValue(new ApiError('drifted', 409))

        logic.actions.approveMetric('weekly_active_users')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allMetrics[0].status).toEqual('proposed')
        const errorCall = (lemonToast.error as jest.Mock).mock.calls.at(-1)
        expect(errorCall?.[1]?.button?.label).toEqual('Refresh from insight')
    })

    it('asks before it overwrites a taken name from the insight modal', async () => {
        const overwritten = buildMetric({ description: 'Overwritten' })
        ;(dataCatalogMetricsCreate as jest.Mock)
            .mockRejectedValueOnce(
                new ApiError('taken', 409, undefined, {
                    code: 'metric_name_taken',
                    extra: { existing_metric: { name: 'weekly_active_users', status: 'approved' } },
                })
            )
            .mockResolvedValueOnce(overwritten)

        logic.actions.openMetricFromInsightModal()
        logic.actions.createMetricFromInsight(
            {
                name: 'weekly_active_users',
                display_name: '',
                description: 'Weekly active users',
                unit: '',
                source_insight_short_id: 'abc123',
            },
            true
        )
        await expectLogic(logic).toFinishAllListeners()

        expect((dataCatalogMetricsCreate as jest.Mock).mock.calls[0][1].overwrite).toBe(false)
        expect(lemonToast.error).not.toHaveBeenCalled()
        expect(logic.values.metricFromInsightModalOpen).toEqual(true)
        const { existing, onOverwrite } = (openOverwriteMetricDialog as jest.Mock).mock.calls[0][0]
        expect(existing).toEqual({ name: 'weekly_active_users', status: 'approved' })

        onOverwrite()
        await expectLogic(logic).toFinishAllListeners()

        expect((dataCatalogMetricsCreate as jest.Mock).mock.calls[1][1]).toMatchObject({
            name: 'weekly_active_users',
            created_source: 'user',
            overwrite: true,
        })
        expect(logic.values.metricFromInsightModalOpen).toEqual(false)
        expect(logic.values.allMetrics).toEqual([overwritten])
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

    it.each([
        ['creator', 'createdBy', 'created_by'],
        ['owner', 'owner', 'owner'],
    ] as const)(
        'filters by %s and reports the filter change once typing settles',
        async (_label, filterKey, property) => {
            const me = userLogic.values.user?.uuid as string
            const myEmail = userLogic.values.user?.email as string
            const filterValue = filterKey === 'createdBy' ? me : myEmail
            const mine = buildMetric({
                id: 'metric-1',
                name: 'mine',
                created_by: { id: 1, uuid: me, email: myEmail, hedgehog_config: null },
                owner: myEmail,
            })
            const theirs = buildMetric({
                id: 'metric-2',
                name: 'theirs',
                created_by: { id: 2, uuid: 'someone-else', email: 'them@example.com', hedgehog_config: null },
                owner: 'them@example.com',
            })
            logic.actions.loadMetricsSuccess([mine, theirs])
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick'] })
            try {
                logic.actions.setFilters({ [filterKey]: filterValue })
                expect(logic.values.metrics).toEqual([mine])
                expect(capture).not.toHaveBeenCalled()

                await jest.advanceTimersByTimeAsync(500)
                expect(capture).toHaveBeenCalledWith(
                    'data catalog metrics filtered',
                    expect.objectContaining({ changed_filters: [filterKey], [property]: 'me', result_count: 1 })
                )

                logic.actions.setFilters({ [filterKey]: null })
                expect(logic.values.metrics).toEqual([mine, theirs])
            } finally {
                jest.useRealTimers()
                capture.mockRestore()
            }
        }
    )

    it('offers the owners of the metrics as owner filter options, so a former member stays listed', async () => {
        logic.actions.loadMetricsSuccess([
            buildMetric({ id: 'metric-1', name: 'a', owner: 'rose.dawson@posthog.com' }),
            buildMetric({ id: 'metric-2', name: 'b', owner: 'former.member@posthog.com' }),
            buildMetric({ id: 'metric-3', name: 'c', owner: null }),
            buildMetric({ id: 'metric-4', name: 'd', owner: 'rose.dawson@posthog.com' }),
        ])

        expect(logic.values.ownerFilterOptions).toEqual(['former.member@posthog.com', 'rose.dawson@posthog.com'])

        logic.actions.setFilters({ owner: 'former.member@posthog.com' })
        expect(logic.values.metrics.map((metric) => metric.name)).toEqual(['b'])
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

    it('gives the selected rows their new owner and clears the selection', async () => {
        logic.actions.loadMetricsSuccess([
            buildMetric({ id: 'metric-1', name: 'first' }),
            buildMetric({ id: 'metric-2', name: 'second' }),
        ])
        ;(dataCatalogMetricsBulkChangeOwnerCreate as jest.Mock).mockResolvedValue({
            updated: [buildMetric({ id: 'metric-1', name: 'first', owner: 'rose.dawson@posthog.com' })],
            skipped: [],
        })
        const onSuccess = jest.fn()

        logic.actions.bulkChangeMetricOwner(['first'], 'rose.dawson@posthog.com', onSuccess)
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogMetricsBulkChangeOwnerCreate).toHaveBeenCalledWith('1', {
            names: ['first'],
            owner: 'rose.dawson@posthog.com',
        })
        expect(logic.values.allMetrics.map((metric) => [metric.name, metric.owner])).toEqual([
            ['first', 'rose.dawson@posthog.com'],
            ['second', null],
        ])
        expect(onSuccess).toHaveBeenCalled()
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
        logic.actions.createMetricFromInsight(
            {
                name: 'from_insight',
                display_name: '',
                description: 'Snapshotted from an insight',
                unit: '',
                source_insight_short_id: 'abc123',
            },
            false
        )
        await expectLogic(logic).toFinishAllListeners()

        const body = (dataCatalogMetricsCreate as jest.Mock).mock.calls.at(-1)?.[1]
        expect(body.source_insight_short_id).toEqual('abc123')
        expect(body.definition).toBeUndefined()
        expect(logic.values.metricFromInsightModalOpen).toEqual(false)
        expect(logic.values.allMetrics.map((metric) => metric.name)).toContain('from_insight')
    })
})
