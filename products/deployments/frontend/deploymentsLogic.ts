import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { deploymentsLogicType } from './deploymentsLogicType'
import {
    DEFAULT_DEPLOYMENT_FILTERS,
    Deployment,
    DEPLOYMENTS_PER_PAGE,
    DeploymentProject,
    DeploymentsFilters,
    DeploymentStatus,
} from './fixtures'
import {
    deploymentProjectsDeploymentsList,
    deploymentProjectsDeploymentsRedeployCreate,
    deploymentProjectsDeploymentsRetrieve,
    deploymentProjectsDeploymentsRollbackCreate,
    deploymentProjectsList,
} from './generated/api'
import type { DeploymentApi, DeploymentProjectApi, PaginatedDeploymentListApi } from './generated/api.schemas'

const filtersFromParams = (params: Record<string, any>): Partial<DeploymentsFilters> => {
    const out: Partial<DeploymentsFilters> = {}
    if (typeof params.search === 'string') {
        out.search = params.search
    }
    if (typeof params.author === 'string' && params.author) {
        out.author = params.author
    }
    if (typeof params.order === 'string') {
        out.order = params.order
    }
    if (params.page !== undefined) {
        const page = parseInt(String(params.page))
        if (!isNaN(page)) {
            out.page = page
        }
    }
    if (typeof params.status === 'string') {
        out.status = params.status.split(',').filter(Boolean) as DeploymentStatus[]
    } else if (Array.isArray(params.status)) {
        out.status = params.status as DeploymentStatus[]
    }
    return out
}

const filtersToParams = (filters: DeploymentsFilters, projectId: string | null): Record<string, string | number> => {
    const params: Record<string, string | number> = {}
    if (projectId) {
        params.project = projectId
    }
    if (filters.search) {
        params.search = filters.search
    }
    if (filters.author) {
        params.author = filters.author
    }
    if (filters.order !== DEFAULT_DEPLOYMENT_FILTERS.order) {
        params.order = filters.order
    }
    if (filters.page > 1) {
        params.page = filters.page
    }
    if (filters.status.length > 0) {
        params.status = filters.status.join(',')
    }
    return params
}

/**
 * Build the query params the backend `DeploymentViewSet.safely_get_queryset`
 * reads. Beyond `limit`/`offset`/`ordering`/`search` (typed in
 * `DeploymentProjectsDeploymentsListParams`), the viewset also accepts
 * `status` (comma-separated) and `author` (single email, icontains).
 * The generated URL builder iterates over all entries so we can pass the
 * extras with a cast.
 */
const buildListQueryParams = (filters: DeploymentsFilters, pageSize: number): Record<string, string | number> => {
    const offset = (filters.page - 1) * pageSize
    const params: Record<string, string | number> = {
        limit: pageSize,
        offset,
        ordering: filters.order,
    }
    if (filters.search.trim()) {
        params.search = filters.search.trim()
    }
    if (filters.author) {
        params.author = filters.author
    }
    if (filters.status.length > 0) {
        params.status = filters.status.join(',')
    }
    return params
}

export const deploymentsLogic = kea<deploymentsLogicType>([
    path(['products', 'deployments', 'frontend', 'deploymentsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        setFilters: (filters: Partial<DeploymentsFilters>) => ({ filters }),
        resetFilters: true,
        setSelectedProjectId: (projectId: string | null) => ({ projectId }),
        redeployDeployment: (id: string) => ({ id }),
        rollbackDeployment: (id: string) => ({ id }),
    }),
    reducers({
        filters: [
            DEFAULT_DEPLOYMENT_FILTERS,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                    page:
                        filters.page ??
                        (filters.search !== undefined || filters.status !== undefined || filters.author !== undefined
                            ? 1
                            : state.page),
                }),
                resetFilters: () => DEFAULT_DEPLOYMENT_FILTERS,
                setSelectedProjectId: () => DEFAULT_DEPLOYMENT_FILTERS,
            },
        ],
        selectedProjectId: [
            null as string | null,
            {
                setSelectedProjectId: (_, { projectId }) => projectId,
            },
        ],
    }),
    loaders(({ values }) => ({
        deploymentProjects: [
            [] as DeploymentProjectApi[],
            {
                loadDeploymentProjects: async (): Promise<DeploymentProjectApi[]> => {
                    const teamId = values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const response = await deploymentProjectsList(String(teamId), { limit: 100 })
                    return response.results ?? []
                },
            },
        ],
        deploymentsResponse: [
            null as PaginatedDeploymentListApi | null,
            {
                loadDeployments: async (): Promise<PaginatedDeploymentListApi | null> => {
                    const teamId = values.currentTeamId
                    const projectId = values.selectedProjectId
                    if (!teamId || !projectId) {
                        return null
                    }
                    return deploymentProjectsDeploymentsList(
                        String(teamId),
                        projectId,
                        buildListQueryParams(values.filters, DEPLOYMENTS_PER_PAGE) as any
                    )
                },
            },
        ],
        // The currently-serving deployment is fetched separately by ID so it
        // stays visible no matter which page or filter combination the user
        // is on — otherwise pagination / a status filter that excludes it
        // would hide the CurrentDeploymentCard.
        currentDeployment: [
            null as DeploymentApi | null,
            {
                loadCurrentDeployment: async (): Promise<DeploymentApi | null> => {
                    const teamId = values.currentTeamId
                    const projectId = values.selectedProjectId
                    const currentId = values.selectedProject?.current_deployment ?? null
                    if (!teamId || !projectId || !currentId) {
                        return null
                    }
                    return deploymentProjectsDeploymentsRetrieve(String(teamId), projectId, currentId)
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        loadDeploymentProjectsSuccess: ({ deploymentProjects }) => {
            // Auto-select the first project if none is selected yet. The
            // selection persists in `selectedProjectId` so subsequent
            // filter changes don't bounce the picker.
            if (!values.selectedProjectId && deploymentProjects.length > 0) {
                actions.setSelectedProjectId(deploymentProjects[0].id)
            }
        },
        setSelectedProjectId: () => {
            actions.loadDeployments()
            actions.loadCurrentDeployment()
        },
        setFilters: () => {
            actions.loadDeployments()
        },
        resetFilters: () => {
            actions.loadDeployments()
        },
        redeployDeployment: async ({ id }) => {
            const teamId = values.currentTeamId
            const projectId = values.selectedProjectId
            if (!teamId || !projectId) {
                return
            }
            try {
                await deploymentProjectsDeploymentsRedeployCreate(String(teamId), projectId, id)
                actions.loadDeployments()
                actions.loadCurrentDeployment()
            } catch (e: any) {
                lemonToast.error(`Failed to redeploy: ${e?.message ?? 'unknown error'}`)
            }
        },
        rollbackDeployment: async ({ id }) => {
            const teamId = values.currentTeamId
            const projectId = values.selectedProjectId
            if (!teamId || !projectId) {
                return
            }
            try {
                await deploymentProjectsDeploymentsRollbackCreate(String(teamId), projectId, id)
                actions.loadDeployments()
                actions.loadCurrentDeployment()
            } catch (e: any) {
                lemonToast.error(`Failed to roll back: ${e?.message ?? 'unknown error'}`)
            }
        },
    })),
    selectors({
        deployments: [
            (s) => [s.deploymentsResponse],
            (response: PaginatedDeploymentListApi | null): DeploymentApi[] => response?.results ?? [],
        ],
        deploymentsCount: [
            (s) => [s.deploymentsResponse],
            (response: PaginatedDeploymentListApi | null): number => response?.count ?? 0,
        ],
        deploymentsLoading: [(s) => [s.deploymentsResponseLoading], (loading: boolean): boolean => loading],
        selectedProject: [
            (s) => [s.deploymentProjects, s.selectedProjectId],
            (projects: DeploymentProjectApi[], id: string | null): DeploymentProjectApi | null =>
                id ? (projects.find((p) => p.id === id) ?? null) : null,
        ],
        authorOptions: [
            (s) => [s.deployments],
            (rows: DeploymentApi[]): { label: string; value: string }[] => {
                const seen = new Map<string, string>()
                rows.forEach((d) => {
                    const email = d.commit_author_email ?? ''
                    const name = d.commit_author_name ?? ''
                    if (email && !seen.has(email)) {
                        seen.set(email, name || email)
                    }
                })
                return Array.from(seen.entries())
                    .map(([email, name]) => ({ label: name, value: email }))
                    .sort((a, b) => a.label.localeCompare(b.label))
            },
        ],
        hasActiveFilters: [
            (s) => [s.filters],
            (filters: DeploymentsFilters): boolean => !!filters.search || !!filters.author || filters.status.length > 0,
        ],
        shouldShowEmptyState: [
            (s) => [
                s.deployments,
                s.deploymentsLoading,
                s.hasActiveFilters,
                s.deploymentProjects,
                s.deploymentProjectsLoading,
            ],
            (
                rows: DeploymentApi[],
                loading: boolean,
                hasFilters: boolean,
                projects: DeploymentProjectApi[],
                projectsLoading: boolean
            ): boolean => {
                if (loading || projectsLoading) {
                    return false
                }
                // No projects yet → onboarding empty state.
                if (projects.length === 0) {
                    return true
                }
                // Project selected with zero deployments and no filters applied.
                return rows.length === 0 && !hasFilters
            },
        ],
        hasNoProjects: [
            (s) => [s.deploymentProjects, s.deploymentProjectsLoading],
            (projects: DeploymentProjectApi[], loading: boolean): boolean => !loading && projects.length === 0,
        ],
    }),
    actionToUrl(({ values }) => {
        const updateUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            return [
                router.values.location.pathname,
                filtersToParams(values.filters, values.selectedProjectId),
                router.values.hashParams,
                { replace: true },
            ]
        }
        return {
            setFilters: updateUrl,
            resetFilters: updateUrl,
            setSelectedProjectId: updateUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.deployments()]: (_, searchParams) => {
            // Adopt project from URL on cold-start.
            if (typeof searchParams.project === 'string' && searchParams.project !== values.selectedProjectId) {
                actions.setSelectedProjectId(searchParams.project)
            }
            const next = filtersFromParams(searchParams)
            const merged = { ...DEFAULT_DEPLOYMENT_FILTERS, ...next }
            if (!objectsEqual(merged, values.filters)) {
                actions.setFilters(merged)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDeploymentProjects()
    }),
])

// Re-export for callers that still import from this module.
export type { Deployment, DeploymentProject, DeploymentsFilters, DeploymentStatus }
export { DEFAULT_DEPLOYMENT_FILTERS }
