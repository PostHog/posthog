import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { Breadcrumb } from '~/types'

import { CATEGORY_ORDER, HEALTH_CATEGORY_CONFIG, categoryForKind } from './healthCategories'
import type { healthSceneLogicType } from './healthSceneLogicType'
import type { CategoryHealthSummary, HealthIssue, HealthIssueSeverity } from './types'

export interface HealthIssuesResponse {
    results: HealthIssue[]
    count: number
    next?: string | null
    previous?: string | null
}

export const healthSceneLogic = kea<healthSceneLogicType>([
    path(['scenes', 'health', 'healthSceneLogic']),
    tabAwareScene(),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setShowDismissed: (show: boolean) => ({ show }),
        dismissIssue: (id: string) => ({ id }),
        undismissIssue: (id: string) => ({ id }),
        refreshHealthData: true,
        resetManualRefresh: true,
    }),
    reducers({
        showDismissed: [
            false,
            {
                setShowDismissed: (_, { show }) => show,
            },
        ],
        isManualRefresh: [
            false,
            {
                refreshHealthData: () => true,
                resetManualRefresh: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        healthIssues: [
            null as HealthIssuesResponse | null,
            {
                loadHealthIssues: async (): Promise<HealthIssuesResponse | null> => {
                    if (!values.unifiedHealthPageEnabled) {
                        return null
                    }
                    const params: Record<string, string> = { status: 'active' }
                    if (!values.showDismissed) {
                        params.dismissed = 'false'
                    }

                    const queryString = new URLSearchParams(params).toString()
                    const url = `api/environments/@current/health_issues/?${queryString}`

                    return await api.get(url)
                },
            },
        ],
    })),
    selectors({
        unifiedHealthPageEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.UNIFIED_HEALTH_PAGE],
        ],
        issues: [
            (s) => [s.healthIssues],
            (healthIssues: HealthIssuesResponse | null): HealthIssue[] => healthIssues?.results ?? [],
        ],
        totalCount: [
            (s) => [s.healthIssues],
            (healthIssues: HealthIssuesResponse | null): number => healthIssues?.count ?? 0,
        ],
        categorySummaries: [
            (s) => [s.issues],
            (issues: HealthIssue[]): CategoryHealthSummary[] => {
                const SEVERITY_RANK: Record<HealthIssueSeverity, number> = {
                    critical: 0,
                    warning: 1,
                    info: 2,
                }

                const countByCategory: Record<string, number> = {}
                const worstByCategory: Record<string, HealthIssueSeverity> = {}

                for (const issue of issues) {
                    const category = categoryForKind(issue.kind)
                    countByCategory[category] = (countByCategory[category] ?? 0) + 1
                    const current = worstByCategory[category]
                    if (!current || SEVERITY_RANK[issue.severity] < SEVERITY_RANK[current]) {
                        worstByCategory[category] = issue.severity
                    }
                }

                const summaries: CategoryHealthSummary[] = []
                for (const category of CATEGORY_ORDER) {
                    if (category === 'other') {
                        continue
                    }
                    const count = countByCategory[category] ?? 0
                    const config = HEALTH_CATEGORY_CONFIG[category]
                    if (!config.showInSummary && count === 0) {
                        continue
                    }
                    summaries.push({
                        category,
                        issueCount: count,
                        worstSeverity: worstByCategory[category] ?? null,
                    })
                }
                return summaries
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Health,
                    name: sceneConfigurations[Scene.Health].name,
                    iconType: sceneConfigurations[Scene.Health].iconType || 'default_icon_type',
                },
            ],
        ],
    }),
    listeners(({ actions, values }) => ({
        refreshHealthData: () => {
            actions.loadHealthIssues()
        },
        loadHealthIssuesSuccess: () => {
            if (values.isManualRefresh) {
                lemonToast.success('Health data refreshed', { autoClose: 1500 })
                actions.resetManualRefresh()
            }
        },
        setShowDismissed: () => {
            actions.loadHealthIssues()
        },
        dismissIssue: async ({ id }) => {
            try {
                await api.update(`api/environments/@current/health_issues/${id}/`, { dismissed: true })
                actions.loadHealthIssues()
            } catch {
                lemonToast.error('Failed to dismiss issue')
            }
        },
        undismissIssue: async ({ id }) => {
            try {
                await api.update(`api/environments/@current/health_issues/${id}/`, { dismissed: false })
                actions.loadHealthIssues()
            } catch {
                lemonToast.error('Failed to undismiss issue')
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.unifiedHealthPageEnabled) {
            actions.loadHealthIssues()
        }
    }),
])
