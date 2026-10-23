import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
    usage_updated_at: null,
    trends: [],
}

describe('modelsUsageLogic', () => {
    let logic: ReturnType<typeof modelsUsageLogic.build>
    let jobRequests: URLSearchParams[]

    beforeEach(() => {
        jobRequests = []
        useMocks({
            get: {
                '/api/projects/:team_id/data_modeling_usage/': emptyUsage,
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

    it('loads all engines and independently filters and pages jobs', async () => {
        await expectLogic(logic).toDispatchActions(['loadUsageSuccess', 'loadMaterializationJobsSuccess'])

        expect(jobRequests[0].get('all_engines')).toBe('true')
        expect(jobRequests[0].get('saved_query_id')).toBeNull()
        expect(logic.values.materializedViewOptions.map((option) => option.name)).toEqual(['Alpha view', 'Beta view'])
        expect(logic.values.savedQueryNameById['view-c']).toBe('Former materialized view')

        await expectLogic(logic, () => logic.actions.setSelectedSavedQueryId('view-a')).toDispatchActions([
            'loadMaterializationJobsSuccess',
        ])
        expect(jobRequests.at(-1)?.get('saved_query_id')).toBe('view-a')
        expect(jobRequests.at(-1)?.get('offset')).toBe('0')

        await expectLogic(logic, () => logic.actions.setJobsPage(2)).toDispatchActions([
            'loadMaterializationJobsSuccess',
        ])
        expect(jobRequests.at(-1)?.get('saved_query_id')).toBe('view-a')
        expect(jobRequests.at(-1)?.get('offset')).toBe('20')
        expect(logic.values.page).toBe(1)
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
        expect(jobRequests.at(-1)?.has('all_engines')).toBe(false)
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
