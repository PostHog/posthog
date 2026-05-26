import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import type { deploymentsLogicType } from './deploymentsLogicType'
import { Deployment, DeploymentProject, DeploymentsFilters, DeploymentStatus } from './fixtures'
import {
    deploymentProjectsDeploymentsList,
    deploymentProjectsDeploymentsRetrieve,
    deploymentProjectsList,
} from './generated/api'
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
        // Map of projectId → the deployment currently serving traffic, used
        // by the grid view. Fetched by id (when the project has a
        // `current_deployment`) so the card reflects what's live — list[0]
        // would return the most recent build, which is wrong after a rollback.
        // Falls back to the newest deployment for never-deployed projects.
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
                                if (p.current_deployment) {
                                    return [
                                        p.id,
                                        await deploymentProjectsDeploymentsRetrieve(
                                            String(teamId),
                                            p.id,
                                            p.current_deployment
                                        ),
                                    ]
                                }
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
