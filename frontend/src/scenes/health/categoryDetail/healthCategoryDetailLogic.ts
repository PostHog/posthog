import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { unifiedHealthMenuLogic } from 'lib/components/HealthMenu/unifiedHealthMenuLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { HEALTH_CATEGORY_CONFIG, kindsForCategory } from '../healthCategories'
import type { HealthIssueCategory } from '../healthCategories'
import type { HealthIssuesResponse } from '../healthSceneLogic'
import { kindToLabel, worstSeverity as computeWorstSeverity } from '../healthUtils'
import type { HealthIssue, HealthIssueSeverity } from '../types'
import { CATEGORY_DETAIL_CONFIG } from './categoryDetailConfig'
import type { healthCategoryDetailLogicType } from './healthCategoryDetailLogicType'

export interface HealthCategoryDetailLogicProps {
    category: string
}

export interface KindGroup {
    kind: string
    label: string
    issues: HealthIssue[]
    worstSeverity: HealthIssueSeverity
}

export const healthCategoryDetailLogic = kea<healthCategoryDetailLogicType>([
    path((key) => ['scenes', 'health', 'categoryDetail', 'healthCategoryDetailLogic', key]),
    props({} as HealthCategoryDetailLogicProps),
    key((props) => props.category),

    connect({
        values: [teamLogic, ['currentTeamIdStrict']],
    }),

    actions({
        setShowDismissed: (show: boolean) => ({ show }),
        dismissIssue: (id: string) => ({ id }),
        undismissIssue: (id: string) => ({ id }),
        refreshHealthData: true,
    }),

    reducers({
        showDismissed: [
            false,
            {
                setShowDismissed: (_, { show }) => show,
            },
        ],
    }),

    loaders(({ values }) => ({
        healthIssues: [
            null as HealthIssuesResponse | null,
            {
                loadHealthIssues: async (): Promise<HealthIssuesResponse | null> => {
                    const params: Record<string, string> = { status: 'active' }
                    if (!values.showDismissed) {
                        params.dismissed = 'false'
                    }

                    const queryString = new URLSearchParams(params).toString()
                    const url = `api/environments/${values.currentTeamIdStrict}/health_issues/?${queryString}`
                    try {
                        return await api.get(url)
                    } catch {
                        lemonToast.error('Failed to load health issues')
                        return values.healthIssues
                    }
                },
            },
        ],
    })),

    selectors({
        category: [() => [(_, props) => props.category], (category: string): string => category],

        isValidCategory: [(s) => [s.category], (category: string): boolean => category in HEALTH_CATEGORY_CONFIG],

        categoryConfig: [
            (s) => [s.category],
            (category: string) => HEALTH_CATEGORY_CONFIG[category as HealthIssueCategory],
        ],

        detailConfig: [
            (s) => [s.category],
            (category: string) => CATEGORY_DETAIL_CONFIG[category as HealthIssueCategory],
        ],

        categoryIssues: [
            (s) => [s.healthIssues, s.category],
            (healthIssues: HealthIssuesResponse | null, category: string): HealthIssue[] => {
                if (!healthIssues) {
                    return []
                }
                const kinds: Set<string> = new Set(kindsForCategory(category as HealthIssueCategory))
                return healthIssues.results.filter((issue) => kinds.has(issue.kind))
            },
        ],

        issuesByKind: [
            (s) => [s.categoryIssues],
            (categoryIssues: HealthIssue[]): KindGroup[] => {
                const grouped: Record<string, HealthIssue[]> = {}
                for (const issue of categoryIssues) {
                    if (!grouped[issue.kind]) {
                        grouped[issue.kind] = []
                    }
                    grouped[issue.kind].push(issue)
                }

                return Object.entries(grouped).map(([kind, issues]) => ({
                    kind,
                    label: kindToLabel(kind),
                    issues,
                    worstSeverity: computeWorstSeverity(issues),
                }))
            },
        ],

        statusSummary: [
            (s) => [s.categoryIssues],
            (
                categoryIssues: HealthIssue[]
            ): { count: number; worstSeverity: HealthIssueSeverity | null; isHealthy: boolean } => {
                if (categoryIssues.length === 0) {
                    return { count: 0, worstSeverity: null, isHealthy: true }
                }
                return {
                    count: categoryIssues.length,
                    worstSeverity: computeWorstSeverity(categoryIssues),
                    isHealthy: false,
                }
            },
        ],

        breadcrumbs: [
            (s) => [s.categoryConfig],
            (categoryConfig: { label: string; description: string } | undefined): Breadcrumb[] => [
                {
                    key: Scene.Health,
                    name: 'Health',
                    path: urls.health(),
                },
                {
                    key: Scene.HealthCategoryDetail,
                    name: categoryConfig?.label ?? 'Detail',
                },
            ],
        ],
    }),

    listeners(({ actions, values }) => ({
        refreshHealthData: () => {
            actions.loadHealthIssues()
        },
        setShowDismissed: () => {
            actions.loadHealthIssues()
        },
        dismissIssue: async ({ id }) => {
            try {
                await api.update(`api/environments/${values.currentTeamIdStrict}/health_issues/${id}/`, {
                    dismissed: true,
                })
                actions.loadHealthIssues()
                unifiedHealthMenuLogic.actions.loadHealthSummary()
            } catch {
                lemonToast.error('Failed to dismiss issue')
            }
        },
        undismissIssue: async ({ id }) => {
            try {
                await api.update(`api/environments/${values.currentTeamIdStrict}/health_issues/${id}/`, {
                    dismissed: false,
                })
                actions.loadHealthIssues()
                unifiedHealthMenuLogic.actions.loadHealthSummary()
            } catch {
                lemonToast.error('Failed to undismiss issue')
            }
        },
    })),

    afterMount(({ actions, props: logicProps }) => {
        if (!(logicProps.category in HEALTH_CATEGORY_CONFIG)) {
            router.actions.replace(urls.health())
            return
        }
        const redirectUrl = CATEGORY_DETAIL_CONFIG[logicProps.category as HealthIssueCategory]?.redirectUrl
        if (redirectUrl) {
            router.actions.replace(redirectUrl)
            return
        }
        actions.loadHealthIssues()
    }),
])
