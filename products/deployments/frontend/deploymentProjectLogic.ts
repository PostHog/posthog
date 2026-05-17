import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { deploymentProjectLogicType } from './deploymentProjectLogicType'
import { deploymentsLogic } from './deploymentsLogic'
import { DEFAULT_DEPLOYMENT_FILTERS, DEPLOYMENTS_PER_PAGE, DeploymentsFilters, DeploymentStatus } from './fixtures'
import {
    deploymentProjectsDeploymentsList,
    deploymentProjectsDeploymentsRedeployCreate,
    deploymentProjectsDeploymentsRetrieve,
    deploymentProjectsDeploymentsRollbackCreate,
} from './generated/api'
import type { DeploymentApi, DeploymentProjectApi, PaginatedDeploymentListApi } from './generated/api.schemas'

export interface DeploymentProjectLogicProps {
    projectId: string
}

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

const filtersToParams = (filters: DeploymentsFilters): Record<string, string | number> => {
    const params: Record<string, string | number> = {}
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

export const deploymentProjectLogic = kea<deploymentProjectLogicType>([
    props({} as DeploymentProjectLogicProps),
    key((p) => p.projectId),
    path((projectId) => ['products', 'deployments', 'frontend', 'deploymentProjectLogic', projectId]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], deploymentsLogic, ['deploymentProjects', 'deploymentProjectsLoading']],
        actions: [deploymentsLogic, ['loadDeploymentProjects']],
    })),
    actions({
        setFilters: (filters: Partial<DeploymentsFilters>) => ({ filters }),
        resetFilters: true,
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
            },
        ],
    }),
    loaders(({ values, props }) => ({
        deploymentsResponse: [
            null as PaginatedDeploymentListApi | null,
            {
                loadDeployments: async (): Promise<PaginatedDeploymentListApi | null> => {
                    const teamId = values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return deploymentProjectsDeploymentsList(
                        String(teamId),
                        props.projectId,
                        buildListQueryParams(values.filters, DEPLOYMENTS_PER_PAGE) as any
                    )
                },
            },
        ],
        // Fetched by id so the currently-serving deployment stays visible on
        // any filter / pagination state — otherwise a status filter that
        // excludes it would hide the CurrentDeploymentCard.
        currentDeployment: [
            null as DeploymentApi | null,
            {
                loadCurrentDeployment: async (): Promise<DeploymentApi | null> => {
                    const teamId = values.currentTeamId
                    const currentId = values.deploymentProject?.current_deployment ?? null
                    if (!teamId || !currentId) {
                        return null
                    }
                    return deploymentProjectsDeploymentsRetrieve(String(teamId), props.projectId, currentId)
                },
            },
        ],
    })),
    listeners(({ actions, values, props }) => ({
        setFilters: () => {
            actions.loadDeployments()
        },
        resetFilters: () => {
            actions.loadDeployments()
        },
        redeployDeployment: async ({ id }) => {
            const teamId = values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await deploymentProjectsDeploymentsRedeployCreate(String(teamId), props.projectId, id)
                actions.loadDeployments()
                actions.loadCurrentDeployment()
            } catch (e: any) {
                lemonToast.error(`Failed to redeploy: ${e?.message ?? 'unknown error'}`)
            }
        },
        rollbackDeployment: async ({ id }) => {
            const teamId = values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await deploymentProjectsDeploymentsRollbackCreate(String(teamId), props.projectId, id)
                actions.loadDeployments()
                actions.loadCurrentDeployment()
            } catch (e: any) {
                lemonToast.error(`Failed to roll back: ${e?.message ?? 'unknown error'}`)
            }
        },
        loadDeploymentProjectsSuccess: () => {
            // Refresh current deployment once we know which project we're bound to.
            if (values.deploymentProject?.current_deployment) {
                actions.loadCurrentDeployment()
            }
        },
    })),
    selectors(({ props }) => ({
        deploymentProject: [
            (s) => [s.deploymentProjects],
            (projects: DeploymentProjectApi[]): DeploymentProjectApi | null =>
                projects.find((p) => p.id === props.projectId) ?? null,
        ],
        deployments: [
            (s) => [s.deploymentsResponse],
            (response: PaginatedDeploymentListApi | null): DeploymentApi[] => response?.results ?? [],
        ],
        deploymentsCount: [
            (s) => [s.deploymentsResponse],
            (response: PaginatedDeploymentListApi | null): number => response?.count ?? 0,
        ],
        deploymentsLoading: [(s) => [s.deploymentsResponseLoading], (loading: boolean): boolean => loading],
        hasActiveFilters: [
            (s) => [s.filters],
            (filters: DeploymentsFilters): boolean => !!filters.search || !!filters.author || filters.status.length > 0,
        ],
        shouldShowEmptyState: [
            (s) => [s.deployments, s.deploymentsLoading, s.hasActiveFilters],
            (rows: DeploymentApi[], loading: boolean, hasFilters: boolean): boolean => {
                if (loading) {
                    return false
                }
                return rows.length === 0 && !hasFilters
            },
        ],
    })),
    actionToUrl(({ values, props }) => {
        const updateUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            return [
                urls.deploymentProject(props.projectId),
                filtersToParams(values.filters),
                router.values.hashParams,
                { replace: true },
            ]
        }
        return {
            setFilters: updateUrl,
            resetFilters: updateUrl,
        }
    }),
    urlToAction(({ actions, values, props }) => ({
        [urls.deploymentProject(':projectId')]: (params, searchParams) => {
            if (params.projectId !== props.projectId) {
                return
            }
            const next = filtersFromParams(searchParams)
            const merged = { ...DEFAULT_DEPLOYMENT_FILTERS, ...next }
            if (!objectsEqual(merged, values.filters)) {
                actions.setFilters(merged)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        // `deploymentsLogic` mounts first via `connect()`, and its own
        // `afterMount` already triggers `loadDeploymentProjects`. Without
        // the loading guard this `afterMount` would issue a redundant
        // parallel request on cold start.
        if (values.deploymentProjects.length === 0 && !values.deploymentProjectsLoading) {
            actions.loadDeploymentProjects()
        }
        actions.loadDeployments()
        if (values.deploymentProject?.current_deployment) {
            actions.loadCurrentDeployment()
        }
    }),
])
