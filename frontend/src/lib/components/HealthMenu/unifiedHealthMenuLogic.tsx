import { afterMount, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import type { HealthIssueSummary } from 'scenes/health/types'

import type { unifiedHealthMenuLogicType } from './unifiedHealthMenuLogicType'

const REFRESH_INTERVAL = 60 * 1000 * 5

export const unifiedHealthMenuLogic = kea<unifiedHealthMenuLogicType>([
    path(['lib', 'components', 'HealthMenu', 'unifiedHealthMenuLogic']),
    loaders(() => ({
        healthSummary: [
            null as HealthIssueSummary | null,
            {
                loadHealthSummary: async (): Promise<HealthIssueSummary | null> => {
                    try {
                        return await api.get('api/environments/@current/health_issues/summary/')
                    } catch {
                        return null
                    }
                },
            },
        ],
    })),
    selectors({
        totalIssues: [(s) => [s.healthSummary], (summary: HealthIssueSummary | null): number => summary?.total ?? 0],
        criticalCount: [
            (s) => [s.healthSummary],
            (summary: HealthIssueSummary | null): number => summary?.by_severity?.critical ?? 0,
        ],
        warningCount: [
            (s) => [s.healthSummary],
            (summary: HealthIssueSummary | null): number => summary?.by_severity?.warning ?? 0,
        ],
        triggerBadgeContent: [(s) => [s.totalIssues], (totalIssues: number): string => (totalIssues > 0 ? '!' : '✓')],
        triggerBadgeStatus: [
            (s) => [s.criticalCount, s.warningCount],
            (criticalCount: number, warningCount: number): 'danger' | 'warning' | 'success' => {
                if (criticalCount > 0) {
                    return 'danger'
                }
                if (warningCount > 0) {
                    return 'warning'
                }
                return 'success'
            },
        ],
    }),
    listeners(({ actions, cache }) => ({
        loadHealthSummarySuccess: () => {
            cache.disposables.add(() => {
                const timerId = setTimeout(() => actions.loadHealthSummary(), REFRESH_INTERVAL)
                return () => clearTimeout(timerId)
            }, 'refreshTimeout')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadHealthSummary()
    }),
])
