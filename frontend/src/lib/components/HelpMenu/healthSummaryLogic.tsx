import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import type { HealthIssueSummary } from 'scenes/health/types'
import { teamLogic } from 'scenes/teamLogic'

import type { healthSummaryLogicType } from './healthSummaryLogicType'

const REFRESH_INTERVAL = 60 * 1000 * 5

export const healthSummaryLogic = kea<healthSummaryLogicType>([
    path(['lib', 'components', 'HelpMenu', 'healthSummaryLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamIdStrict']] })),
    loaders(({ values }) => ({
        healthSummary: [
            null as HealthIssueSummary | null,
            {
                loadHealthSummary: async (): Promise<HealthIssueSummary | null> => {
                    try {
                        return await api.get(`api/environments/${values.currentTeamIdStrict}/health_issues/summary/`)
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
