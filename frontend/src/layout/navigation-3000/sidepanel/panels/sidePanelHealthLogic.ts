import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { sidePanelHealthLogicType } from './sidePanelHealthLogicType'

export type HealthStatus = 'danger' | 'warning' | 'success'

export interface DataHealthIssue {
    id: string
    name: string
    type: 'materialized_view' | 'external_data_sync' | 'source' | 'destination' | 'transformation'
    source_type?: string | null
    status: 'failed' | 'disabled' | 'degraded' | 'billing_limit'
    error: string | null
    failed_at: string | null
    url: string | null
}

export interface DataHealthIssuesResponse {
    results: DataHealthIssue[]
    count: number
}

export const REFRESH_INTERVAL = 60 * 1000 * 5 // 5 minutes

export const sidePanelHealthLogic = kea<sidePanelHealthLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelHealthLogic']),

    actions({
        setPageVisibility: (visible: boolean) => ({ visible }),
    }),

    reducers(() => ({
        issueCount: [
            0,
            { persist: true },
            {
                loadHealthIssuesSuccess: (_, { healthIssues }) => healthIssues?.count ?? 0,
                loadHealthIssuesFailure: () => 0,
            },
        ],
    })),

    loaders(() => ({
        healthIssues: [
            null as DataHealthIssuesResponse | null,
            {
                loadHealthIssues: async (): Promise<DataHealthIssuesResponse | null> => {
                    try {
                        const response = await api.get<DataHealthIssuesResponse>(
                            'api/environments/@current/data_warehouse/data_health_issues/'
                        )
                        return response
                    } catch (error) {
                        console.error('Error loading health issues', error)
                        return null
                    }
                },
            },
        ],
    })),

    selectors({
        hasIssues: [
            (s) => [s.issueCount],
            (issueCount: number): boolean => {
                return issueCount > 0
            },
        ],

        healthStatus: [
            (s) => [s.issueCount],
            (issueCount: number): HealthStatus => {
                if (issueCount > 0) {
                    return 'danger'
                }
                return 'success'
            },
        ],

        issues: [
            (s) => [s.healthIssues],
            (healthIssues: DataHealthIssuesResponse | null): DataHealthIssue[] => {
                return healthIssues?.results ?? []
            },
        ],

        hasErrors: [
            (s) => [s.healthIssues, s.healthIssuesLoading],
            (healthIssues: DataHealthIssuesResponse | null, healthIssuesLoading: boolean): boolean => {
                return !healthIssuesLoading && healthIssues === null
            },
        ],
    }),

    listeners(({ actions, cache }) => ({
        loadHealthIssuesSuccess: () => {
            cache.disposables.add(() => {
                const timerId = setTimeout(() => actions.loadHealthIssues(), REFRESH_INTERVAL)
                return () => clearTimeout(timerId)
            }, 'refreshTimeout')
        },
        setPageVisibility: ({ visible }) => {
            if (visible) {
                actions.loadHealthIssues()
            } else {
                cache.disposables.dispose('refreshTimeout')
            }
        },
    })),

    afterMount(({ actions, cache }) => {
        actions.loadHealthIssues()
        cache.disposables.add(() => {
            const onVisibilityChange = (): void => {
                actions.setPageVisibility(document.visibilityState === 'visible')
            }
            document.addEventListener('visibilitychange', onVisibilityChange)
            return () => document.removeEventListener('visibilitychange', onVisibilityChange)
        }, 'visibilityListener')
    }),
])
