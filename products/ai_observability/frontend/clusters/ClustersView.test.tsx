import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ProductEmptyStateGate } from 'lib/components/ProductEmptyState/ProductEmptyStateGate'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { clustersEmptyState } from '../emptyState/clustersEmptyState'
import { clusteringConfigLogic } from './clusteringConfigLogic'
import { ClustersView } from './ClustersView'

describe('ClustersView', () => {
    it('keeps the switch available to turn clustering off and back on', async () => {
        const config = { enabled: true, event_filters: [], created_at: '', updated_at: '' }
        useMocks({
            get: {
                '/api/projects/:teamId/llm_analytics/clustering_config/': () => config,
                '/api/projects/:teamId/llm_analytics/clustering_config/progress/': [],
            },
            post: {
                '/api/projects/:teamId/llm_analytics/clustering_config/set_enabled/': async ({ request }) => {
                    config.enabled = ((await request.json()) as { enabled: boolean }).enabled
                    return config
                },
            },
        })
        initKeaTests()
        window.POSTHOG_APP_CONTEXT!.resource_access_control = {
            ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
            [AccessControlResourceType.AiObservabilityClusters]: AccessControlLevel.Editor,
        }
        const query = jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] })
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        const logic = clusteringConfigLogic()
        logic.mount()
        try {
            await expectLogic(logic).toFinishAllListeners()
            render(<ClustersView />)
            const toggle = await screen.findByLabelText('Clustering enabled')
            expect(toggle).toBeEnabled()
            fireEvent.click(toggle)
            await waitFor(() => expect(config.enabled).toBe(false))
            expect(
                await screen.findByText('Clustering is off. Enable it to start new runs for this project.')
            ).toBeVisible()
            const disabledToggle = screen.getByLabelText('Clustering disabled')
            expect(disabledToggle).not.toBeChecked()
            fireEvent.click(disabledToggle)
            await waitFor(() => expect(config.enabled).toBe(true))
            expect(await screen.findByLabelText('Clustering enabled')).toBeChecked()
        } finally {
            cleanup()
            logic.unmount()
            query.mockRestore()
        }
    })
})

describe('cluster setup and jobs', () => {
    let query: jest.SpyInstance
    let config: { enabled: boolean; event_filters: []; created_at: string; updated_at: string }

    beforeEach(async () => {
        config = { enabled: false, event_filters: [], created_at: '', updated_at: '' }
        useMocks({
            get: {
                '/api/projects/:teamId/llm_analytics/clustering_config/': () => config,
                '/api/projects/:teamId/llm_analytics/clustering_config/progress/': [],
                '/api/projects/:teamId/llm_analytics/clustering_jobs/': {
                    results: [{ id: 1, name: 'All traces', analysis_level: 'trace', event_filters: [], enabled: true }],
                },
            },
            post: {
                '/api/projects/:teamId/llm_analytics/clustering_config/set_enabled/': async ({ request }) => {
                    config.enabled = ((await request.json()) as { enabled: boolean }).enabled
                    return config
                },
            },
        })
        initKeaTests()
        window.POSTHOG_APP_CONTEXT!.resource_access_control = {
            ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
            [AccessControlResourceType.AiObservabilityClusters]: AccessControlLevel.Editor,
        }
        query = jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] })
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        clusteringConfigLogic.mount()
        await expectLogic(clusteringConfigLogic).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
        clusteringConfigLogic.unmount()
        query.mockRestore()
    })

    it.each([
        ['1', 'Original job name', 'All traces'],
        ['deleted-job', 'Archived traces', 'Archived traces'],
        [null, null, 'Unassigned run'],
    ])('identifies the run by its job (%s)', async (jobId, jobName, expectedName) => {
        query.mockImplementation(async (sql) => ({
            results: String(sql).includes('ORDER BY timestamp DESC')
                ? [['1_trace_20260107_120000', '2026-01-07', '2026-01-07T12:00:00Z', jobId, jobName]]
                : [],
        }))
        render(<ClustersView />)
        expect(await screen.findByText(new RegExp(`${expectedName} · Jan 7, 2026`))).toBeVisible()
    })

    it.each(['cluster list', 'waiting screen'])(
        'keeps existing jobs and job creation reachable from the %s',
        async (page) => {
            config.enabled = true
            render(
                page === 'cluster list' ? (
                    <ClustersView />
                ) : (
                    <ProductEmptyStateGate emptyState={clustersEmptyState}>
                        <div>Previous clusters</div>
                    </ProductEmptyStateGate>
                )
            )
            fireEvent.click(await screen.findByText('Jobs (1)'))
            expect(await screen.findByText('All traces')).toBeVisible()
            fireEvent.click(screen.getByText('Add job'))
            expect(await screen.findByText('Create')).toBeVisible()
        }
    )

    it('shows setup only while disabled and a separate waiting page after enabling', async () => {
        render(
            <ProductEmptyStateGate emptyState={clustersEmptyState}>
                <div>Previous clusters</div>
            </ProductEmptyStateGate>
        )
        expect(await screen.findByText('Enable clustering')).toBeVisible()
        expect(screen.queryByText(/Jobs/)).not.toBeInTheDocument()
        fireEvent.click(await screen.findByText('Enable clustering'))
        await waitFor(() => expect(config.enabled).toBe(true))
        expect(await screen.findByText('Clustering is enabled')).toBeVisible()
        expect(screen.queryByText('Find the patterns in how people use your AI')).not.toBeInTheDocument()
        expect(screen.queryByText('Clusters, once your traces are grouped')).not.toBeInTheDocument()
        expect(screen.queryByText('Enable clustering')).not.toBeInTheDocument()
        expect(await screen.findByText('Jobs (1)')).toBeVisible()
        fireEvent.click(screen.getByLabelText('Clustering enabled'))
        expect(await screen.findByText('Enable clustering')).toBeVisible()
        expect(screen.queryByText(/Jobs/)).not.toBeInTheDocument()
        expect(screen.queryByText('Waiting for your first clusters')).not.toBeInTheDocument()
    })

    it.each([false, true])('shows previous clusters when enabled=%s', async (enabled) => {
        config.enabled = enabled
        query.mockResolvedValue({ results: [[1]] })
        render(
            <ProductEmptyStateGate emptyState={clustersEmptyState}>
                <div>Previous clusters</div>
            </ProductEmptyStateGate>
        )
        expect(await screen.findByText('Previous clusters')).toBeVisible()
        expect(screen.queryByText('Enable clustering')).not.toBeInTheDocument()
        expect(screen.queryByText('Waiting for your first clusters')).not.toBeInTheDocument()
    })
})
