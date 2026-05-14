import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { deploymentsLogicType } from './deploymentsLogicType'
import { Deployment, DeploymentProject, DeploymentsFilters, DeploymentStatus } from './fixtures'
import {
    deploymentProjectsDeploymentsList,
    deploymentProjectsDeploymentsRetrieve,
    deploymentProjectsList,
} from './generated/api'
import type { DeploymentApi, DeploymentProjectApi } from './generated/api.schemas'
import { cloneInitialStubDeploymentsByProject, cloneInitialStubProjects, makeStubDeploymentReady } from './stubData'

export const deploymentsLogic = kea<deploymentsLogicType>([
    path(['products', 'deployments', 'frontend', 'deploymentsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
        actions: [featureFlagLogic, ['setFeatureFlags']],
    })),
    actions({
        openAddProjectModal: true,
        closeAddProjectModal: true,
        addStubProject: (project: DeploymentProjectApi, deployment: DeploymentApi | null) => ({ project, deployment }),
        addStubDeployment: (projectId: string, deployment: DeploymentApi) => ({ projectId, deployment }),
        markStubDeploymentReady: (projectId: string, deployment: DeploymentApi) => ({ projectId, deployment }),
    }),
    reducers({
        addProjectModalOpen: [
            false,
            {
                openAddProjectModal: () => true,
                closeAddProjectModal: () => false,
            },
        ],
        stubDeploymentProjects: [
            cloneInitialStubProjects(),
            {
                addStubProject: (state, { project }) => [project, ...state.filter((p) => p.id !== project.id)],
                addStubDeployment: (state, { projectId, deployment }) =>
                    deployment.status === 'ready'
                        ? state.map((project) =>
                              project.id === projectId
                                  ? { ...project, current_deployment: deployment.id, updated_at: deployment.created_at }
                                  : project
                          )
                        : state,
                markStubDeploymentReady: (state, { projectId, deployment }) =>
                    state.map((project) =>
                        project.id === projectId
                            ? {
                                  ...project,
                                  current_deployment: deployment.id,
                                  updated_at: deployment.finished_at ?? deployment.created_at,
                              }
                            : project
                    ),
            },
        ],
        stubDeploymentsByProject: [
            cloneInitialStubDeploymentsByProject(),
            {
                addStubProject: (state, { project, deployment }) => ({
                    ...state,
                    [project.id]: deployment ? [deployment] : [],
                }),
                addStubDeployment: (state, { projectId, deployment }) => ({
                    ...state,
                    [projectId]: [
                        deployment,
                        ...(state[projectId] ?? [])
                            .filter((existing) => existing.id !== deployment.id)
                            .map((existing) =>
                                deployment.status === 'ready' ? { ...existing, is_current: false } : existing
                            ),
                    ],
                }),
                markStubDeploymentReady: (state, { projectId, deployment }) => ({
                    ...state,
                    [projectId]: [
                        deployment,
                        ...(state[projectId] ?? [])
                            .filter((existing) => existing.id !== deployment.id)
                            .map((existing) => ({ ...existing, is_current: false })),
                    ],
                }),
            },
        ],
    }),
    loaders(({ values }) => ({
        deploymentProjects: [
            [] as DeploymentProjectApi[],
            {
                loadDeploymentProjects: async (): Promise<DeploymentProjectApi[]> => {
                    if (values.isStubMode) {
                        return values.stubDeploymentProjects
                    }
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
                    const projects = values.deploymentProjects
                    if (values.isStubMode) {
                        return Object.fromEntries(
                            projects.map((project): [string, DeploymentApi | null] => {
                                const deployments = values.stubDeploymentsByProject[project.id] ?? []
                                return [
                                    project.id,
                                    deployments.find((deployment) => deployment.id === project.current_deployment) ??
                                        deployments[0] ??
                                        null,
                                ]
                            })
                        )
                    }
                    const teamId = values.currentTeamId
                    if (!teamId) {
                        return {}
                    }
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
    listeners(({ actions, values }) => ({
        setFeatureFlags: () => {
            actions.loadDeploymentProjects()
        },
        loadDeploymentProjectsSuccess: () => {
            actions.loadCurrentDeploymentsByProject()
        },
        addStubProject: ({ project, deployment }) => {
            actions.loadDeploymentProjects()
            actions.loadCurrentDeploymentsByProject()
            if (deployment && deployment.status !== 'ready') {
                window.setTimeout(() => {
                    const currentProject = values.stubDeploymentProjects.find((p) => p.id === project.id) ?? project
                    const currentDeployment =
                        values.stubDeploymentsByProject[project.id]?.find((d) => d.id === deployment.id) ?? deployment
                    actions.markStubDeploymentReady(
                        project.id,
                        makeStubDeploymentReady(currentDeployment, currentProject)
                    )
                }, 4500)
            }
        },
        addStubDeployment: ({ projectId, deployment }) => {
            actions.loadDeploymentProjects()
            actions.loadCurrentDeploymentsByProject()
            if (deployment.status !== 'ready') {
                window.setTimeout(() => {
                    const currentProject = values.stubDeploymentProjects.find((p) => p.id === projectId)
                    const currentDeployment =
                        values.stubDeploymentsByProject[projectId]?.find((d) => d.id === deployment.id) ?? deployment
                    if (currentProject) {
                        actions.markStubDeploymentReady(
                            projectId,
                            makeStubDeploymentReady(currentDeployment, currentProject)
                        )
                    }
                }, 4500)
            }
        },
        markStubDeploymentReady: () => {
            actions.loadDeploymentProjects()
            actions.loadCurrentDeploymentsByProject()
        },
    })),
    selectors({
        isStubMode: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.DEPLOYMENTS_STUB],
        ],
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
