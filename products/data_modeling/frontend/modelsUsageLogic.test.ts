import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DataModelingUsageListEngine } from './generated/api.schemas'
import { modelsUsageLogic } from './modelsUsageLogic'

const emptyUsage = {
    date_from: '2026-09-01',
    date_to: '2026-10-01',
    overview: {
        runs: 0,
        measured_runs: 0,
        read_bytes: null,
        read_rows: null,
        cpu_microseconds: null,
        query_count: null,
    },
    models: [],
    count: 0,
    status_breakdown: [],
    usage_updated_at: null,
    trends: [],
}

describe('modelsUsageLogic', () => {
    let logic: ReturnType<typeof modelsUsageLogic.build>
    let jobRequests: URLSearchParams[]
    let usageRequests: URLSearchParams[]

    beforeEach(() => {
        jobRequests = []
        usageRequests = []
        useMocks({
            get: {
                '/api/projects/:team_id/data_modeling_usage/': ({ request }) => {
                    usageRequests.push(new URL(request.url).searchParams)
                    return [200, emptyUsage]
                },
                '/api/projects/:team_id/data_modeling_jobs/': ({ request }) => {
                    jobRequests.push(new URL(request.url).searchParams)
                    return [200, { count: 0, next: null, previous: null, results: [] }]
                },
                '/api/projects/:team_id/warehouse_saved_queries/': {
                    count: 2,
                    results: [
                        { id: 'view-b', name: 'Beta view', is_materialized: true },
                        { id: 'view-a', name: 'Alpha view', is_materialized: true },
                        { id: 'view-c', name: 'Former materialized view', is_materialized: false },
                    ],
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.DATA_MODELING_USAGE]: true,
            [FEATURE_FLAGS.MANAGED_TRINO_QUERY]: true,
        })
        logic = modelsUsageLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('filters usage and jobs by model across the whole tab', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        expect(usageRequests[0].get('engine')).toBe('all')
        expect(jobRequests[0].get('all_engines')).toBe('true')
        expect(jobRequests[0].get('engine')).toBeNull()
        expect(jobRequests[0].get('saved_query_ids')).toBeNull()
        expect(jobRequests[0].get('after')).not.toBeNull()
        expect(jobRequests[0].get('before')).toBeNull()
        expect(logic.values.materializedViewOptions.map((option) => option.name)).toEqual(['Alpha view', 'Beta view'])

        await expectLogic(logic, () => logic.actions.setSelectedSavedQueryIds(['view-a', 'view-b'])).toDispatchActions([
            'loadUsageSuccess',
            'loadMaterializationJobsSuccess',
        ])
        expect(usageRequests.at(-1)?.get('saved_query_ids')).toBe('view-a,view-b')
        expect(jobRequests.at(-1)?.get('saved_query_ids')).toBe('view-a,view-b')
        expect(jobRequests.at(-1)?.get('offset')).toBe('0')

        await expectLogic(logic, () => logic.actions.setJobsPage(2)).toDispatchActions([
            'loadMaterializationJobsSuccess',
        ])
        expect(jobRequests.at(-1)?.get('saved_query_ids')).toBe('view-a,view-b')
        expect(jobRequests.at(-1)?.get('offset')).toBe('20')
        expect(logic.values.page).toBe(1)
    })

    it('sorts all models, resets pagination, and keeps the sort on the next page', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])
        await expectLogic(logic, () => logic.actions.setPage(3)).toDispatchActions(['loadUsageSuccess'])
        const jobRequestCount = jobRequests.length

        await expectLogic(logic, () => logic.actions.sortModels('runs')).toDispatchActions(['loadUsageSuccess'])
        expect(usageRequests.at(-1)?.get('page')).toBe('1')
        expect(usageRequests.at(-1)?.get('sort_by')).toBe('runs')
        expect(usageRequests.at(-1)?.get('sort_direction')).toBe('desc')
        await expectLogic(logic, () => logic.actions.sortModels('runs')).toDispatchActions(['loadUsageSuccess'])
        expect(usageRequests.at(-1)?.get('sort_direction')).toBe('asc')
        await expectLogic(logic, () => logic.actions.setPage(2)).toDispatchActions(['loadUsageSuccess'])
        expect(usageRequests.at(-1)?.get('page')).toBe('2')
        expect(usageRequests.at(-1)?.get('sort_by')).toBe('runs')
        expect(usageRequests.at(-1)?.get('sort_direction')).toBe('asc')
        await expectLogic(logic, () => logic.actions.sortModels('name')).toDispatchActions(['loadUsageSuccess'])
        expect(usageRequests.at(-1)?.get('sort_direction')).toBe('asc')
        expect(jobRequests).toHaveLength(jobRequestCount)

        await expectLogic(logic, () => logic.actions.sortModels('managed_warehouse_read_bytes')).toDispatchActions([
            'loadUsageSuccess',
        ])
        await expectLogic(logic, () =>
            logic.actions.setSelectedEngine(DataModelingUsageListEngine.Clickhouse)
        ).toDispatchActions(['loadUsageSuccess'])
        expect(usageRequests.at(-1)?.get('sort_by')).toBe('read_bytes')
        expect(usageRequests.at(-1)?.get('sort_direction')).toBe('desc')
    })

    it('builds a status breakdown by engine', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess'])

        logic.actions.loadUsageSuccess({
            ...emptyUsage,
            status_breakdown: [
                { engine: 'clickhouse', status: 'Completed', count: 3, models: [] },
                { engine: 'clickhouse', status: 'Failed', count: 1, models: [] },
                { engine: 'managed_warehouse', status: 'Failed', count: 2, models: [] },
            ],
        })

        expect(logic.values.statusChartLabels).toEqual(['Completed', 'Failed'])
        expect(logic.values.statusChartSeries).toEqual([
            { key: 'clickhouse', label: 'ClickHouse', data: [3, 1] },
            { key: 'managed_warehouse', label: 'Managed warehouse', data: [0, 2] },
        ])

        expect(logic.values.selectedSavedQueryIds).toEqual([])
    })

    it('keeps selected status models that are absent from the materialized view options', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])
        await expectLogic(logic, () => logic.actions.setSelectedSavedQueryIds(['deleted-view'])).toDispatchActions([
            'loadUsageSuccess',
            'loadMaterializationJobsSuccess',
        ])

        logic.actions.loadUsageSuccess({
            ...emptyUsage,
            status_breakdown: [
                {
                    engine: 'clickhouse',
                    status: 'Failed',
                    count: 1,
                    models: [
                        {
                            saved_query_id: 'deleted-view',
                            name: 'Deleted view',
                            deleted: true,
                        },
                    ],
                },
            ],
        })

        expect(logic.values.viewFilterOptions).toContainEqual({ id: 'deleted-view', name: 'Deleted view' })
        expect(logic.values.selectedMaterializedViewOptions).toEqual([{ id: 'deleted-view', name: 'Deleted view' }])

        logic.actions.setSelectedSavedQueryIds(['deleted-view', 'view-a'])
        expect(logic.values.selectedMaterializedViewOptions).toEqual([
            { id: 'deleted-view', name: 'Deleted view' },
            { id: 'view-a', name: 'Alpha view' },
        ])
    })

    it('filters all tab requests by engine', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        await expectLogic(logic, () =>
            logic.actions.setSelectedEngine(DataModelingUsageListEngine.ManagedWarehouse)
        ).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        expect(usageRequests.at(-1)?.get('engine')).toBe('managed_warehouse')
        expect(jobRequests.at(-1)?.get('all_engines')).toBe('true')
        expect(jobRequests.at(-1)?.get('engine')).toBe('managed_warehouse')
        expect(logic.values.page).toBe(1)
        expect(logic.values.jobsPage).toBe(1)
    })

    it('filters usage and jobs by a custom date range', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        await expectLogic(logic, () =>
            logic.actions.setDateRange('2026-10-01T00:00:00', '2026-10-07T23:59:59')
        ).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        expect(usageRequests.at(-1)?.get('days')).toBeNull()
        expect(usageRequests.at(-1)?.get('date_from')).toBe('2026-10-01')
        expect(usageRequests.at(-1)?.get('date_to')).toBe('2026-10-07')
        expect(jobRequests.at(-1)?.get('after')).toBe('2026-10-01T00:00:00.000Z')
        expect(jobRequests.at(-1)?.get('before')).toBeNull()
        expect(logic.values.page).toBe(1)
        expect(logic.values.jobsPage).toBe(1)
    })

    it('normalizes picker timestamps and limits custom ranges to complete days', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        await expectLogic(logic, () =>
            logic.actions.setDateRange('2024-01-01T00:00:00.000Z', '9999-12-31T23:59:59.999Z')
        ).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        const yesterday = dayjs.utc().subtract(1, 'day').format('YYYY-MM-DD')
        const earliestDate = dayjs.utc().startOf('day').subtract(366, 'day').format('YYYY-MM-DD')
        expect(logic.values.dateFrom).toBe(earliestDate)
        expect(logic.values.dateTo).toBe(yesterday)
        expect(usageRequests.at(-1)?.get('date_from')).toBe(earliestDate)
        expect(usageRequests.at(-1)?.get('date_to')).toBe(yesterday)
    })

    it('filters materialization jobs by status', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])
        const usageRequestCount = usageRequests.length

        await expectLogic(logic, () => logic.actions.setSelectedJobStatus('Failed')).toDispatchActions([
            'loadMaterializationJobsSuccess',
        ])

        expect(jobRequests.at(-1)?.get('status')).toBe('Failed')
        expect(usageRequests).toHaveLength(usageRequestCount)
        expect(logic.values.jobsPage).toBe(1)
    })

    it('keeps the jobs query ClickHouse-only when managed warehouse is disabled', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.DATA_MODELING_USAGE]: true,
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: false,
            [FEATURE_FLAGS.MANAGED_TRINO_QUERY]: false,
        })

        await expectLogic(logic, () => logic.actions.refresh()).toDispatchActions(['loadMaterializationJobsSuccess'])

        expect(logic.values.managedWarehouseEnabled).toBe(false)
        expect(usageRequests.at(-1)?.get('engine')).toBe('clickhouse')
        expect(jobRequests.at(-1)?.has('all_engines')).toBe(false)
        expect(jobRequests.at(-1)?.has('engine')).toBe(false)
    })

    it('surfaces model-name lookup failures and retries both job dependencies', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        dataWarehouseViewsLogic.actions.loadDataWarehouseSavedQueriesFailure('Lookup failed')
        expect(logic.values.jobsFailed).toBe(true)

        await expectLogic(logic, () => logic.actions.refreshJobs()).toDispatchActions([
            'loadDataWarehouseSavedQueries',
            'loadMaterializationJobsSuccess',
        ])

        expect(logic.values.jobsFailed).toBe(false)
    })
})
