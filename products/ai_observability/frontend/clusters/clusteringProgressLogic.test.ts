import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ClusteringJobProgressApi } from '../generated/api.schemas'
import { clusteringConfigLogic } from './clusteringConfigLogic'
import { clusteringJobsLogic } from './clusteringJobsLogic'
import { clusteringProgressLogic } from './clusteringProgressLogic'
import { clustersLogic } from './clustersLogic'

const completedJob: ClusteringJobProgressApi = {
    job_id: '0192f200-0000-7000-8000-000000000001',
    name: 'Traces',
    analysis_level: 'trace',
    has_filters: false,
    minimum: 10,
    lookback_days: 7,
    status: 'completed',
    eligible_count: 10,
    prepared_count: 10,
    cluster_count: 1,
    failure_reason: '',
    updated_at: '2026-11-13T12:00:00Z',
    result_run_id: 'new-run',
}

describe('clustering progress updates', () => {
    let progress: ClusteringJobProgressApi[]

    beforeEach(async () => {
        progress = [{ ...completedJob }]
        useMocks({
            get: {
                '/api/projects/:teamId/llm_analytics/clustering_config/': { enabled: true, event_filters: [] },
                '/api/projects/:teamId/llm_analytics/clustering_config/progress/': () => progress,
                '/api/projects/:teamId/llm_analytics/clustering_jobs/': { results: [] },
            },
            post: {
                '/api/projects/:teamId/llm_analytics/clustering_jobs/': () => {
                    progress = [{ ...completedJob, status: 'queued' }]
                    return {}
                },
            },
            patch: {
                '/api/projects/:teamId/llm_analytics/clustering_jobs/:id/': () => {
                    progress = [{ ...completedJob, status: 'queued' }]
                    return {}
                },
            },
        })
        initKeaTests()
        teamLogic.mount()
        clusteringConfigLogic.mount()
        clusteringJobsLogic.mount()
        clusteringProgressLogic.mount()
        await expectLogic(clusteringProgressLogic).toFinishAllListeners()
        await expectLogic(clusteringConfigLogic).toFinishAllListeners()
        await expectLogic(clusteringJobsLogic).toFinishAllListeners()
    })

    afterEach(() => {
        clusteringProgressLogic.unmount()
        clusteringJobsLogic.unmount()
        clusteringConfigLogic.unmount()
        teamLogic.unmount()
        jest.useRealTimers()
    })

    it.each(['create', 'update'])('refreshes a terminal progress list after job %s', async (mutation) => {
        if (mutation === 'create') {
            clusteringJobsLogic.actions.createJob({ name: 'Another job', analysis_level: 'trace' })
        } else {
            clusteringJobsLogic.actions.updateJob({ id: 1, enabled: true })
        }
        await expectLogic(clusteringJobsLogic).toFinishAllListeners()
        await expectLogic(clusteringProgressLogic).toFinishAllListeners()
        expect(clusteringProgressLogic.values.progress[0].status).toBe('queued')
    })

    it('keeps discovering a completed result until ingestion makes it queryable', async () => {
        let visible = false
        const query = jest.spyOn(api, 'queryHogQL').mockImplementation(async (sql) => ({
            results: String(sql).includes('$ai_clusters')
                ? []
                : [
                      ['old-run', '2026-11-12', '2026-11-12T12:00:00Z', completedJob.job_id, 'Traces'],
                      ...(visible
                          ? [['new-run', '2026-11-13', '2026-11-13T12:00:00Z', completedJob.job_id, 'Traces']]
                          : []),
                  ],
        }))
        const clusters = clustersLogic()
        clusters.mount()
        try {
            await expectLogic(clusters).toFinishAllListeners()
            clusteringProgressLogic.unmount()
            jest.useFakeTimers()
            clusteringProgressLogic.mount()
            await expectLogic(clusteringProgressLogic).toFinishAllListeners()
            await jest.advanceTimersByTimeAsync(10000)
            await expectLogic(clusters).toFinishAllListeners()
            expect(clusters.values.clusteringRuns.map(({ runId }) => runId)).toEqual(['old-run'])
            visible = true
            await jest.advanceTimersByTimeAsync(10000)
            await expectLogic(clusters).toFinishAllListeners()
            expect(clusters.values.clusteringRuns.map(({ runId }) => runId)).toContain('new-run')
        } finally {
            clusters.unmount()
            query.mockRestore()
        }
    })
})
