import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import { catalogRunsList, catalogRunsSyncCreate } from 'products/catalog/frontend/generated/api'
import type { CatalogTraversalRunDTOApi } from 'products/catalog/frontend/generated/api.schemas'

import type { catalogLogsSceneLogicType } from './catalogLogsSceneLogicType'

const RUN_POLL_INTERVAL_MS = 5000

export const catalogLogsSceneLogic = kea<catalogLogsSceneLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogLogsSceneLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setSelectedRunId: (runId: string | null) => ({ runId }),
        startSync: true,
        syncStarted: true,
        syncFailed: true,
        startPolling: true,
        stopPolling: true,
    }),

    reducers({
        selectedRunId: [null as string | null, { setSelectedRunId: (_, { runId }) => runId }],
        syncing: [false, { startSync: () => true, syncStarted: () => false, syncFailed: () => false }],
    }),

    loaders(({ values }) => ({
        runs: [
            [] as CatalogTraversalRunDTOApi[],
            {
                loadRuns: async () => {
                    const projectId = String(values.currentProjectId)
                    const page = await catalogRunsList(projectId)
                    return page.results
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                { key: 'catalog', name: 'Semantic layer' },
                { key: 'logs', name: 'Logs' },
            ],
        ],
        selectedRun: [
            (s) => [s.runs, s.selectedRunId],
            (runs, selectedRunId): CatalogTraversalRunDTOApi | null => {
                if (!selectedRunId) {
                    return runs[0] ?? null
                }
                return runs.find((r) => r.id === selectedRunId) ?? null
            },
        ],
        hasInFlightRun: [
            (s) => [s.runs],
            (runs): boolean => runs.some((r) => r.status === 'queued' || r.status === 'running'),
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        startSync: async () => {
            try {
                await catalogRunsSyncCreate(String(values.currentProjectId))
                actions.syncStarted()
                actions.loadRuns()
            } catch {
                actions.syncFailed()
            }
        },
        loadRunsSuccess: () => {
            if (values.hasInFlightRun) {
                actions.startPolling()
            } else {
                actions.stopPolling()
            }
        },
        startPolling: () => {
            cache.disposables.add(() => {
                const id = window.setInterval(() => actions.loadRuns(), RUN_POLL_INTERVAL_MS)
                return () => clearInterval(id)
            }, 'runsPolling')
        },
        stopPolling: () => {
            cache.disposables.dispose('runsPolling')
        },
    })),

    urlToAction(({ actions }) => ({
        '/catalog/logs': () => {
            actions.loadRuns()
        },
    })),
])
