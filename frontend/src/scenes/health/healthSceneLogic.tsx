import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { healthSummaryLogic } from 'lib/components/HelpMenu/healthSummaryLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import { CATEGORY_ORDER, HEALTH_CATEGORY_CONFIG, categoryForKind } from './healthCategories'
import type { healthSceneLogicType } from './healthSceneLogicType'
import type { CategoryHealthSummary, HealthIssue, HealthIssueSeverity } from './types'
import { REFRESH_COOLDOWN_MS, REFRESH_POLL_COUNT, REFRESH_POLL_INTERVAL_MS, SEVERITY_ORDER } from './types'

export interface HealthIssuesResponse {
    results: HealthIssue[]
    count: number
    next?: string | null
    previous?: string | null
}

export const healthSceneLogic = kea<healthSceneLogicType>([
    path(['scenes', 'health', 'healthSceneLogic']),
    connect({
        values: [teamLogic, ['currentTeamIdStrict']],
    }),
    actions({
        setShowDismissed: (show: boolean) => ({ show }),
        dismissIssue: (id: string) => ({ id }),
        undismissIssue: (id: string) => ({ id }),
        refreshHealthData: (isManual: boolean = true) => ({ isManual }),
        resetManualRefresh: true,
        setNextRefreshAvailableAt: (timestamp: number | null) => ({ timestamp }),
        clearRefreshInFlight: true,
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
                refreshHealthData: (_, { isManual }) => isManual,
                resetManualRefresh: () => false,
            },
        ],
        nextRefreshAvailableAt: [
            null as number | null,
            { persist: true },
            {
                setNextRefreshAvailableAt: (_, { timestamp }) => timestamp,
            },
        ],
        isRefreshInFlight: [
            false,
            {
                refreshHealthData: (state, { isManual }) => (isManual ? true : state),
                clearRefreshInFlight: () => false,
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

                    return await api.get(url)
                },
            },
        ],
    })),
    selectors({
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
                const countByCategory: Record<string, number> = {}
                const worstByCategory: Record<string, HealthIssueSeverity> = {}

                for (const issue of issues) {
                    const category = categoryForKind(issue.kind)
                    countByCategory[category] = (countByCategory[category] ?? 0) + 1
                    const current = worstByCategory[category]
                    if (!current || SEVERITY_ORDER.indexOf(issue.severity) < SEVERITY_ORDER.indexOf(current)) {
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
        refreshHealthData: async ({ isManual }, breakpoint) => {
            const url = `api/environments/${values.currentTeamIdStrict}/health_issues/refresh/`
            try {
                const response = await api.create<{
                    scheduled_kinds: string[]
                    kinds_failed: string[]
                    team_id: number
                }>(url)
                breakpoint()

                actions.setNextRefreshAvailableAt(Date.now() + REFRESH_COOLDOWN_MS)

                if ((response?.scheduled_kinds ?? []).length === 0) {
                    actions.clearRefreshInFlight()
                    actions.resetManualRefresh()
                    if (isManual) {
                        lemonToast.info('No health checks are registered for this project.')
                    }
                    return
                }

                if (isManual) {
                    lemonToast.success('Refreshing health checks...', { autoClose: 2000 })
                }

                for (let i = 0; i < REFRESH_POLL_COUNT; i++) {
                    await breakpoint(REFRESH_POLL_INTERVAL_MS)
                    actions.loadHealthIssues()
                }
                actions.clearRefreshInFlight()
            } catch (error: unknown) {
                actions.clearRefreshInFlight()
                actions.resetManualRefresh()
                if (error instanceof ApiError && error.status === 429) {
                    const retryAfterSeconds = Number(error.headers?.get('Retry-After'))
                    if (!isNaN(retryAfterSeconds) && retryAfterSeconds > 0) {
                        actions.setNextRefreshAvailableAt(Date.now() + retryAfterSeconds * 1000)
                    }
                    if (isManual) {
                        lemonToast.warning(`Refresh available again ${error.formattedRetryAfter ?? 'in a few minutes'}`)
                    }
                } else if (isManual) {
                    lemonToast.error('Failed to refresh health checks')
                }
            }
        },
        setNextRefreshAvailableAt: async ({ timestamp }, breakpoint) => {
            if (timestamp === null) {
                return
            }
            const delay = timestamp - Date.now()
            if (delay <= 0) {
                actions.setNextRefreshAvailableAt(null)
                return
            }
            await breakpoint(delay)
            actions.setNextRefreshAvailableAt(null)
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
                await api.update(`api/environments/${values.currentTeamIdStrict}/health_issues/${id}/`, {
                    dismissed: true,
                })
                actions.loadHealthIssues()
                healthSummaryLogic.actions.loadHealthSummary()
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
                healthSummaryLogic.actions.loadHealthSummary()
            } catch {
                lemonToast.error('Failed to undismiss issue')
            }
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadHealthIssues()

        const { nextRefreshAvailableAt } = values
        if (nextRefreshAvailableAt === null || nextRefreshAvailableAt <= Date.now()) {
            actions.refreshHealthData(false)
        }

        if (values.nextRefreshAvailableAt !== null) {
            actions.setNextRefreshAvailableAt(values.nextRefreshAvailableAt)
        }
    }),
])
