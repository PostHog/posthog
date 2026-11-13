import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ClusteringJobProgressApi } from '../generated/api.schemas'
import { clusteringConfigLogic } from './clusteringConfigLogic'
import { ClusteringProgress } from './ClusteringProgress'

const traceJob: ClusteringJobProgressApi = {
    job_id: '0192f200-0000-7000-8000-000000000001',
    name: 'All traces',
    analysis_level: 'trace',
    has_filters: false,
    minimum: 10,
    lookback_days: 7,
    status: 'waiting',
    eligible_count: 0,
    prepared_count: 0,
    cluster_count: null,
    failure_reason: '',
    updated_at: '2026-11-13T12:00:00Z',
}

describe('first clustering run progress', () => {
    let jobs: ClusteringJobProgressApi[]
    let retried: string | undefined

    beforeEach(async () => {
        jobs = [{ ...traceJob }]
        retried = undefined
        useMocks({
            get: {
                '/api/projects/:teamId/llm_analytics/clustering_config/': {
                    enabled: true,
                    event_filters: [],
                    created_at: '',
                    updated_at: '',
                },
                '/api/projects/:teamId/llm_analytics/clustering_config/progress/': () => jobs,
            },
            post: {
                '/api/projects/:teamId/llm_analytics/clustering_config/retry/': async ({ request }) => {
                    retried = ((await request.json()) as { job_id: string }).job_id
                    jobs = jobs.map((job) => ({ ...job, status: 'preparing', failure_reason: '' }))
                    return jobs
                },
            },
        })
        initKeaTests()
        window.POSTHOG_APP_CONTEXT!.resource_access_control = {
            ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
            [AccessControlResourceType.AiObservabilityClusters]: AccessControlLevel.Editor,
        }
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        clusteringConfigLogic.mount()
        await expectLogic(clusteringConfigLogic).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
        clusteringConfigLogic.unmount()
        teamLogic.unmount()
    })

    it('explains the minimum and directs a project without traces to instrumentation', async () => {
        render(<ClusteringProgress />)
        expect(await screen.findByText('0 of 10')).toBeVisible()
        expect(screen.getByText('Needs 10 traces in the last 7 days.')).toBeVisible()
        expect(screen.getByRole('link', { name: 'Set up AI tracing' })).toHaveAttribute(
            'href',
            'https://posthog.com/docs/llm-analytics/installation'
        )
        expect(screen.getByText(/every 30 minutes/)).toBeVisible()
    })

    it('explains job filters and the independent evaluation requirement', async () => {
        jobs = [
            {
                ...traceJob,
                analysis_level: 'evaluation',
                lookback_days: 3,
                has_filters: true,
                name: 'Support evaluations',
            },
        ]
        render(<ClusteringProgress />)
        expect(
            await screen.findByText(
                'Needs 10 evaluations in the last 3 days that match this job’s filters. Numeric and categorical results aren’t included.'
            )
        ).toBeVisible()
        expect(screen.getByText(/trace and generation jobs can run without them/)).toBeVisible()
        expect(screen.queryByRole('link', { name: 'Set up AI tracing' })).not.toBeInTheDocument()
    })

    it('retries a failed job and shows its new processing state', async () => {
        jobs = [{ ...traceJob, status: 'failed', failure_reason: 'processing_failed' }]
        render(<ClusteringProgress />)
        fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))
        await waitFor(() => expect(retried).toBe(traceJob.job_id))
        expect(await screen.findByText('Preparing data')).toBeVisible()
        expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    })

    it('treats a completed run without groups as a result rather than ongoing work', async () => {
        jobs = [{ ...traceJob, status: 'completed', cluster_count: 0 }]
        render(<ClusteringProgress />)
        expect(await screen.findByText('No groups found')).toBeVisible()
        expect(screen.getByText(/There wasn’t enough similarity/)).toBeVisible()
        expect(screen.queryByText('Finding clusters')).not.toBeInTheDocument()
    })
})
