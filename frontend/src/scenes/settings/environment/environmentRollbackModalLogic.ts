import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { OrganizationType } from '~/types'

import type { environmentRollbackModalLogicType } from './environmentRollbackModalLogicType'

export interface Team {
    id: number
    name: string
    project_id: number
}

export interface ProjectWithEnvironments {
    id: number
    name: string
    environments: Team[]
}

export const environmentRollbackModalLogic = kea<environmentRollbackModalLogicType>([
    path(['scenes', 'settings', 'environment', 'environmentRollbackModalLogic']),
    connect(() => ({
        values: [
            organizationLogic,
            ['currentOrganization', 'currentOrganizationLoading', 'isAdminOrOwner'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions({
        openModal: true,
        closeModal: true,
        setProjectEnvironment: (projectId: number, environmentId: number | null) => ({ projectId, environmentId }),
        submitEnvironmentRollback: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        selectedEnvironments: [
            {} as Record<number, number | null>,
            {
                setProjectEnvironment: (state, { projectId, environmentId }) => ({
                    ...state,
                    [projectId]: environmentId,
                }),
                closeModal: () => ({}),
            },
        ],
    }),
    selectors(() => ({
        hasEnvironmentsRollbackFeature: [
            (s) => [s.featureFlags, s.projectsWithEnvironments, organizationLogic.selectors.isAdminOrOwner],
            (
                featureFlags: FeatureFlagsSet,
                projectsWithEnvironments: ProjectWithEnvironments[],
                isAdminOrOwner: boolean | null
            ): boolean => {
                const hasFeatureFlags =
                    !!featureFlags[FEATURE_FLAGS.ENVIRONMENTS_ROLLBACK] && !!featureFlags[FEATURE_FLAGS.ENVIRONMENTS]
                const hasMultiEnvProjects = projectsWithEnvironments.length > 0

                return hasFeatureFlags && hasMultiEnvProjects && !!isAdminOrOwner
            },
        ],
        // Get all projects with their environments
        projectsWithEnvironments: [
            (s) => [s.currentOrganization, s.currentOrganizationLoading],
            (
                currentOrganization: OrganizationType | null,
                currentOrganizationLoading: boolean
            ): ProjectWithEnvironments[] => {
                if (currentOrganizationLoading || !currentOrganization) {
                    return []
                }

                const projectsMap = new Map<number, ProjectWithEnvironments>()

                // Initialize projects
                for (const project of currentOrganization.projects) {
                    projectsMap.set(project.id, {
                        id: project.id,
                        name: project.name,
                        environments: [],
                    })
                }

                // Add environments to their projects
                for (const team of currentOrganization.teams) {
                    const project = projectsMap.get(team.project_id)
                    if (project) {
                        project.environments.push({
                            id: team.id,
                            name: team.name,
                            project_id: team.project_id,
                        })
                    }
                }

                // Filter to only show projects with more than one environment
                return Array.from(projectsMap.values()).filter((project) => project.environments.length > 1)
            },
        ],
        // Count projects that have exactly one environment
        hiddenProjectsCount: [
            (s) => [s.currentOrganization, s.currentOrganizationLoading],
            (currentOrganization: OrganizationType | null, currentOrganizationLoading: boolean): number => {
                if (currentOrganizationLoading || !currentOrganization) {
                    return 0
                }

                const projectsMap = new Map<number, number>() // project_id -> environment count

                // Count environments per project
                for (const team of currentOrganization.teams) {
                    const count = projectsMap.get(team.project_id) || 0
                    projectsMap.set(team.project_id, count + 1)
                }

                // Count projects with exactly one environment
                return Array.from(projectsMap.values()).filter((count) => count === 1).length
            },
        ],
        allEnvironments: [
            (s) => [s.projectsWithEnvironments],
            (projectsWithEnvironments: ProjectWithEnvironments[]): Team[] => {
                return projectsWithEnvironments.flatMap((project) => project.environments)
            },
        ],
        // Format projects and environments as LemonSelect options
        environmentSelectOptions: [
            (s) => [s.projectsWithEnvironments],
            (projectsWithEnvironments: ProjectWithEnvironments[]): LemonSelectOptions<number> => {
                return projectsWithEnvironments.map((project) => ({
                    title: project.name,
                    options: project.environments.map((env) => ({
                        value: env.id,
                        label: env.name,
                    })),
                }))
            },
        ],
        isReadyToSubmit: [
            (s) => [s.selectedEnvironments, s.projectsWithEnvironments],
            (
                selectedEnvironments: Record<number, number | null>,
                projectsWithEnvironments: ProjectWithEnvironments[]
            ): boolean => {
                return projectsWithEnvironments.every((project) => {
                    const selected = selectedEnvironments[project.id]
                    return selected !== undefined && selected !== null
                })
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        openModal: () => {
            if (!values.hasEnvironmentsRollbackFeature) {
                lemonToast.error('Environment rollback feature is not available for your organization')
                return
            }
        },
        submitEnvironmentRollback: async () => {
            if (values.currentOrganizationLoading || !values.currentOrganization) {
                throw new Error('Organization data is not yet loaded')
            }

            if (!values.isReadyToSubmit) {
                lemonToast.error('Please select an environment for each project')
                return
            }

            // For each project, map all OTHER environments to the selected target environment
            const environmentMappings: Record<string, number> = {}
            values.projectsWithEnvironments.forEach((project) => {
                const targetEnvironmentId = values.selectedEnvironments[project.id]
                if (targetEnvironmentId) {
                    project.environments.forEach((env) => {
                        if (env.id !== targetEnvironmentId) {
                            environmentMappings[env.id.toString()] = targetEnvironmentId
                        }
                    })
                }
            })

            try {
                await api.create(
                    `api/organizations/${values.currentOrganization.id}/environments_rollback/`,
                    environmentMappings
                )

                lemonToast.warning(
                    'Environment rollback in progress. You will receive an email when it is completed.',
                    { closeButton: true, autoClose: false }
                )
                actions.closeModal()
                teamLogic.actions.loadCurrentTeam()
            } catch (error: any) {
                lemonToast.error(
                    error.detail || 'Failed to initiate environment rollback. Please try again or contact support.'
                )
            }
        },
    })),
])
