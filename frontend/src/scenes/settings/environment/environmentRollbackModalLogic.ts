import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { OrganizationType } from '~/types'

import type { environmentRollbackModalLogicType } from './environmentRollbackModalLogicType'

export interface Team {
    id: number
    name: string
    access_control: boolean
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
        values: [organizationLogic, ['currentOrganization', 'currentOrganizationLoading']],
    })),
    actions({
        openModal: true,
        closeModal: true,
        setSelectedEnvironmentId: (id: number | null) => ({ id }),
        submitEnvironmentRollback: true,
    }),
    reducers({
        isOpen: [
            true,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        selectedEnvironmentId: [
            null as number | null,
            {
                setSelectedEnvironmentId: (_, { id }) => id,
                closeModal: () => null,
            },
        ],
    }),
    selectors({
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
                            access_control: team.access_control,
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
    }),
    listeners(({ values, actions }) => ({
        submitEnvironmentRollback: async () => {
            if (values.currentOrganizationLoading || !values.currentOrganization) {
                throw new Error('Organization data is not yet loaded')
            }

            if (!values.selectedEnvironmentId) {
                lemonToast.error('Please select a main environment')
                return
            }

            try {
                await api.create(`api/organizations/@current/environments_rollback/`, {
                    main_environment_id: values.selectedEnvironmentId,
                })

                lemonToast.success('Environment rollback initiated successfully')
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
