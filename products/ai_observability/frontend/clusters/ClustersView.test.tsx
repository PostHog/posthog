import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { findChart, getChartTooltip, setupChartTests } from '@posthog/quill-charts/testing'

import api from 'lib/api'
import { ProductEmptyStateGate } from 'lib/components/ProductEmptyState/ProductEmptyStateGate'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, PropertyFilterType, PropertyOperator } from '~/types'

import { clustersEmptyState } from '../emptyState/clustersEmptyState'
import { traceDrawerLogic } from '../redesign/trace/traceDrawerLogic'
import { clusteringConfigLogic } from './clusteringConfigLogic'
import { clustersLogic } from './clustersLogic'
import { ClustersView } from './ClustersView'

describe('ClustersView', () => {
    it('keeps the switch available to turn clustering off and back on', async () => {
        const config = { enabled: true, event_filters: [], created_at: '', updated_at: '' }
        useMocks({
            get: {
                '/api/projects/:teamId/llm_analytics/clustering_config/': () => config,
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
                await screen.findByText('Clustering is off. Enable it to include this project in scheduled runs.')
            ).toBeVisible()
            const disabledToggle = screen.getByLabelText('Clustering disabled')
            expect(disabledToggle).not.toBeChecked()
            expect(
                screen.getByText('No clustering runs yet. Enable clustering to start finding patterns in your data.')
            ).toBeVisible()
            expect(screen.queryByText(/after the first automatic run/)).not.toBeInTheDocument()
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
    setupChartTests()

    let query: jest.SpyInstance
    let config: { enabled: boolean; event_filters: []; created_at: string; updated_at: string }

    beforeEach(async () => {
        config = { enabled: false, event_filters: [], created_at: '', updated_at: '' }
        useMocks({
            get: {
                '/api/projects/:teamId/llm_analytics/clustering_config/': () => config,
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
            await expectLogic(clusteringConfigLogic, () =>
                clusteringConfigLogic.actions.loadConfig()
            ).toFinishAllListeners()
            render(
                page === 'cluster list' ? (
                    <ClustersView />
                ) : (
                    <ProductEmptyStateGate emptyState={clustersEmptyState}>
                        <div>Previous clusters</div>
                    </ProductEmptyStateGate>
                )
            )
            fireEvent.click(await screen.findByText(page === 'waiting screen' ? 'Manage jobs' : 'Jobs (1)'))
            expect(await screen.findByText('All traces')).toBeVisible()
            fireEvent.click(screen.getByText('Add job'))
            expect(await screen.findByText('Create')).toBeVisible()
        }
    )

    it.each<['table' | 'map', boolean]>([
        ['table', false],
        ['table', true],
        ['map', false],
        ['map', true],
    ])('navigates through the visible cluster members from the %s (filtered=%s)', async (source, filtered) => {
        const clusters = [0, 1].map((clusterId) => ({
            cluster_id: clusterId,
            title: `Cluster ${clusterId}`,
            description: '',
            size: 2,
            centroid: [],
            centroid_x: clusterId,
            centroid_y: 0,
            traces: Object.fromEntries(
                [0, 1].map((rank) => {
                    const id = `trace-${clusterId}-${rank}`
                    return [
                        id,
                        {
                            trace_id: id,
                            rank,
                            distance_to_centroid: 0,
                            x: clusterId ? rank * 2 - 1 : rank / 4,
                            y: clusterId ? rank * 2 - 1 : rank / 4,
                            timestamp: '2026-01-07T12:00:00Z',
                        },
                    ]
                })
            ),
        }))
        const runId = '1_trace_20260107_120000'
        query.mockImplementation(async (sql) => ({
            results: String(sql).includes('as total_items')
                ? [
                      [
                          runId,
                          '2026-01-01',
                          '2026-01-07',
                          4,
                          JSON.stringify(clusters),
                          '2026-01-07T12:00:00Z',
                          '{}',
                          'trace',
                      ],
                  ]
                : String(sql).includes('as run_id')
                  ? [[runId, '2026-01-07', '2026-01-07T12:00:00Z']]
                  : String(sql).includes('SELECT DISTINCT')
                    ? [['trace-0-0'], ['trace-1-0'], ['trace-1-1']]
                    : [],
        }))
        router.actions.push(`/ai-observability/clusters/${runId}`)
        render(<ClustersView />)
        await screen.findByText('Cluster 0')
        if (filtered) {
            await act(async () => {
                await expectLogic(clustersLogic, () =>
                    clustersLogic.actions.setPropertyFilters([
                        {
                            type: PropertyFilterType.Event,
                            key: 'environment',
                            value: 'production',
                            operator: PropertyOperator.Exact,
                        },
                    ])
                ).toFinishAllListeners()
            })
        }
        if (source === 'map') {
            const chart = await findChart({ seriesCount: 2 })
            await waitFor(() => {
                fireEvent.mouseMove(chart.element, { clientX: 400, clientY: 200 })
                expect(getChartTooltip()).not.toBeNull()
            })
            fireEvent.click(chart.element)
        } else {
            fireEvent.click((await screen.findAllByTitle('Show more'))[0])
            fireEvent.click((await screen.findAllByText('Trace trace-0-'))[0])
        }
        const drawer = traceDrawerLogic({ listId: 'clusters' })
        await waitFor(() => expect(drawer.values.openTraceId).toBe('trace-0-0'))
        expect(drawer.values.rows.map((row) => row.traceId)).toEqual(
            filtered ? ['trace-0-0'] : ['trace-0-0', 'trace-0-1']
        )
        expect(drawer.values.nextTrace?.traceId ?? null).toBe(filtered ? null : 'trace-0-1')
    })

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
        expect(await screen.findByText('No clusters yet')).toBeVisible()
        expect(screen.queryByText('Find the patterns in how people use your AI')).not.toBeInTheDocument()
        expect(screen.queryByText('Clusters, once your traces are grouped')).not.toBeInTheDocument()
        expect(screen.queryByText('Enable clustering')).not.toBeInTheDocument()
        expect(await screen.findByText('Manage jobs')).toBeVisible()
        fireEvent.click(screen.getByLabelText('Clustering enabled'))
        expect(await screen.findByText('Enable clustering')).toBeVisible()
        expect(screen.queryByText(/Jobs/)).not.toBeInTheDocument()
        expect(screen.queryByText('No clusters yet')).not.toBeInTheDocument()
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
