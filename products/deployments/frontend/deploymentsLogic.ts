import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import type { deploymentsLogicType } from './deploymentsLogicType'
import { Deployment, DeploymentProject, DeploymentsFilters, DeploymentStatus } from './fixtures'
import { deploymentProjectsDeploymentsList, deploymentProjectsList } from './generated/api'
import type { DeploymentApi, DeploymentProjectApi } from './generated/api.schemas'

export const deploymentsLogic = kea<deploymentsLogicType>([
    path(['products', 'deployments', 'frontend', 'deploymentsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        openAddProjectModal: true,
        closeAddProjectModal: true,
    }),
    reducers({
        addProjectModalOpen: [
            false,
            {
                openAddProjectModal: () => true,
                closeAddProjectModal: () => false,
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
        // Map of projectId → its current deployment, used by the grid view.
        // Each project's `current_deployment` field is just an id; we fan out
        // one retrieve-by-id call per project so the cards show the latest
        // commit/preview without loading the full deployment list per project.
        currentDeploymentsByProject: [
            {} as Record<string, DeploymentApi | null>,
            {
                loadCurrentDeploymentsByProject: async (): Promise<Record<string, DeploymentApi | null>> => {
                    const teamId = values.currentTeamId
                    if (!teamId) {
                        return {}
                    }
                    const projects = values.deploymentProjects
                    const entries = await Promise.all(
                        projects.map(async (p): Promise<[string, DeploymentApi | null]> => {
                            try {
                                const list = await deploymentProjectsDeploymentsList(String(teamId), p.id, {
                                    limit: 1,
                                } as any)
                                return [p.id, list.results?.[0] ?? null]
                            } catch {
                                return [p.id, null]
                            }
                        })
                    )
                    return Object.fromEntries(entries)
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadDeploymentProjectsSuccess: () => {
            actions.loadCurrentDeploymentsByProject()
        },
    })),
    selectors({
        hasNoProjects: [
            (s) => [s.deploymentProjects, s.deploymentProjectsLoading],
            (projects: DeploymentProjectApi[], loading: boolean): boolean => !loading && projects.length === 0,
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDeploymentProjects()
    }),
])

// Re-export for callers that still import from this module.
export type { Deployment, DeploymentProject, DeploymentsFilters, DeploymentStatus }
