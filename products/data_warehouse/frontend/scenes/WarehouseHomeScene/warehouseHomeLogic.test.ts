import { expectLogic } from 'kea-test-utils'

import type { ProductSetupStatus } from 'lib/components/ProductEmptyState/types'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dataWarehouseSetupLogic } from '../../emptyState/dataWarehouseSetupLogic'
import { warehouseHomeLogic } from './warehouseHomeLogic'

const ISSUES = {
    count: 4,
    results: [
        {
            id: '1',
            name: 'charges',
            type: 'external_data_sync',
            status: 'degraded',
            error: null,
            failed_at: null,
            url: '/a',
        },
        {
            id: '2',
            name: 'invoices',
            type: 'external_data_sync',
            status: 'failed',
            error: 'boom',
            failed_at: null,
            url: '/b',
        },
        {
            id: '3',
            name: 'hook',
            type: 'external_data_sync',
            sync_type: 'webhook',
            status: 'failed',
            error: null,
            failed_at: null,
            url: null,
        },
        { id: '4', name: 'export', type: 'destination', status: 'failed', error: null, failed_at: null, url: null },
    ],
}

const JOB_STATS = {
    days: 7,
    cutoff_time: '2026-11-16T10:30:00+00:00',
    total_jobs: 10,
    successful_jobs: 9,
    failed_jobs: 1,
    external_data_jobs: { total: 6, running: 0, successful: 5, failed: 1 },
    modeling_jobs: { total: 4, running: 1, successful: 4, failed: 0 },
    breakdown: {},
}

function useWarehouseHomeMocks(overrides: Record<string, any> = {}): void {
    useMocks({
        get: {
            '/api/environments/:team_id/external_data_sources/': { results: [], count: 0 },
            '/api/environments/:team_id/warehouse_tables/': { results: [], count: 0 },
            '/api/projects/:team_id/warehouse_saved_queries/': { results: [], count: 0 },
            '/api/projects/:team_id/data_warehouse/data_health_issues/': ISSUES,
            '/api/projects/:team_id/data_warehouse/completed_activity/': { results: [], next: null, previous: null },
            '/api/projects/:team_id/data_warehouse/running_activity/': { results: [], next: null, previous: null },
            '/api/projects/:team_id/data_warehouse/job_stats/': JOB_STATS,
            ...overrides,
        },
    })
}

describe('warehouseHomeLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('resolves an empty team to unfinished steps, no runs and only warehouse issues, most severe first', async () => {
        useWarehouseHomeMocks()
        const logic = warehouseHomeLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            viewStep: 'todo',
            recentRuns: [],
            healthIssuesFailed: false,
        })
        expect(logic.values.warehouseIssues?.map((issue) => issue.id)).toEqual(['2', '1'])
        expect(logic.values.issueCountsByStatus).toEqual([
            ['failed', 1],
            ['degraded', 1],
        ])
    })

    it('lists a run once, as running, when both endpoints return it', async () => {
        useWarehouseHomeMocks({
            '/api/projects/:team_id/data_warehouse/running_activity/': {
                results: [{ id: 'r1', status: 'Running' }],
                next: null,
                previous: null,
            },
            '/api/projects/:team_id/data_warehouse/completed_activity/': {
                results: [
                    { id: 'r1', status: 'Completed' },
                    { id: 'r2', status: 'Completed' },
                ],
                next: null,
                previous: null,
            },
        })
        const logic = warehouseHomeLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.recentRuns?.map((run) => [run.id, run.status])).toEqual([
            ['r1', 'Running'],
            ['r2', 'Completed'],
        ])
    })

    it('reloads health and runs when the tab becomes visible again', async () => {
        let issues = ISSUES
        let running = [{ id: 'r1', status: 'Running' }]
        useWarehouseHomeMocks({
            '/api/projects/:team_id/data_warehouse/data_health_issues/': () => [200, issues],
            '/api/projects/:team_id/data_warehouse/running_activity/': () => [
                200,
                { results: running, next: null, previous: null },
            ],
        })
        const setVisibility = (state: DocumentVisibilityState): void => {
            Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
            document.dispatchEvent(new Event('visibilitychange'))
        }
        const logic = warehouseHomeLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        issues = { count: 0, results: [] }
        running = []
        setVisibility('hidden')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.warehouseIssues?.map((issue) => issue.id)).toEqual(['2', '1'])

        setVisibility('visible')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.warehouseIssues).toEqual([])
        expect(logic.values.recentRuns).toEqual([])
    })

    test.each<[ProductSetupStatus, string]>([
        ['loading', 'loading'],
        ['unknown', 'todo'],
        ['needs-setup', 'todo'],
        ['waiting-for-data', 'done'],
        ['has-data', 'done'],
    ])('maps setup status %s to source step %s', async (status, expected) => {
        useWarehouseHomeMocks()
        const logic = warehouseHomeLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        dataWarehouseSetupLogic.actions.setDetectedStatus(status)

        expect(logic.values.sourceStep).toBe(expected)
    })

    it('marks the view step done once a saved query exists', async () => {
        useWarehouseHomeMocks({
            '/api/projects/:team_id/warehouse_saved_queries/': { results: [{ id: 'q' }], count: 1 },
        })
        const logic = warehouseHomeLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.viewStep).toBe('done')
    })

    it('keeps the other sections when health issues fail to load', async () => {
        useWarehouseHomeMocks({
            '/api/projects/:team_id/data_warehouse/data_health_issues/': () => [500, { detail: 'nope' }],
        })
        const logic = warehouseHomeLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.healthIssuesFailed).toBe(true)
        expect(logic.values.recentRuns).toEqual([])
        expect(logic.values.viewStep).toBe('todo')
    })

    it('loads the run statistics for the chosen window and derives the tiles', async () => {
        const requestedDays: (string | null)[] = []
        useWarehouseHomeMocks({
            '/api/projects/:team_id/data_warehouse/job_stats/': ({ request }: any) => {
                requestedDays.push(new URL(request.url).searchParams.get('days'))
                return [200, JOB_STATS]
            },
        })
        const logic = warehouseHomeLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.runSuccess).toEqual({ value: '90%', detail: '9 of 10 runs' })
        expect(logic.values.syncTile).toEqual({ value: '6', detail: '1 failed' })
        expect(logic.values.viewTile).toEqual({ value: '4', detail: '1 running' })
        expect(logic.values.attentionTile).toMatchObject({ value: '2', detail: '1 failed, 1 degraded', danger: true })

        await expectLogic(logic, () => logic.actions.setJobStatsDays(30)).toFinishAllListeners()
        expect(requestedDays).toEqual(['7', '30'])
        expect(logic.values.jobStatsDays).toBe(30)
    })
})
