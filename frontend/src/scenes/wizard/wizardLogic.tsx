import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { wizardLogicType } from './wizardLogicType'
import { projectLogic } from 'scenes/projectLogic'

export interface WizardTokenResponseType {
    success: boolean
}

export const wizardLogic = kea<wizardLogicType>([
    path(['scenes', 'wizard', 'wizardLogic']),
    connect(() => ({
        actions: [teamLogic, ['loadCurrentTeamSuccess']],
        values: [
            teamLogic,
            ['currentTeam'],
            organizationLogic,
            ['currentOrganization'],
            projectLogic,
            ['currentProject'],
        ],
    })),
    actions({
        setWizardHash: (wizardHash: string | null) => ({ wizardHash }),
        setView: (view: 'project' | 'pending' | 'success' | 'invalid') => ({ view }),
        setSelectedProject: (projectId: number | null) => ({ projectId }),
        authenticateWizard: (wizardHash: string, projectId: number) => ({ wizardHash, projectId }),
        continueToAuthentication: () => ({}),
    }),
    loaders(({ actions }) => ({
        wizardToken: [
            null as WizardTokenResponseType | null,
            {
                authenticateWizard: async ({ wizardHash, projectId }: { wizardHash: string; projectId: number }) => {
                    try {
                        actions.setView('pending')
                        const response: WizardTokenResponseType = await api.wizard.authenticateWizard({
                            hash: wizardHash,
                            projectId: projectId,
                        })
                        actions.setView('success')
                        return response
                    } catch {
                        actions.setView('invalid')

                        return { success: false }
                    }
                },
            },
        ],
    })),
    reducers({
        wizardHash: [
            null as string | null,
            {
                setWizardHash: (_, { wizardHash }) => wizardHash,
            },
        ],
        view: [
            'project' as 'project' | 'pending' | 'success' | 'invalid',
            {
                setView: (_, { view }) => view,
            },
        ],
        selectedProjectId: [
            null as number | null,
            {
                setSelectedProject: (_, { projectId }) => projectId,
            },
        ],
    }),
    selectors({
        availableProjects: [
            (s) => [s.currentOrganization],
            (currentOrganization) => {
                return (
                    currentOrganization?.teams?.map((team) => ({
                        value: team.id,
                        label: team.name,
                        api_token: team.api_token,
                        organization: currentOrganization.id,
                    })) || []
                )
            },
        ],
        selectedProject: [
            (s) => [s.availableProjects, s.selectedProjectId],
            (availableProjects, selectedProjectId) => {
                return availableProjects.find((project) => project.value === selectedProjectId)
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        continueToAuthentication: () => {
            const projectId = values.selectedProjectId
            const wizardHash = values.wizardHash

            if (!projectId || !wizardHash) {
                console.error('Missing projectId or wizardHash for authentication')
                return
            }

            actions.setView('pending')
            actions.authenticateWizard(wizardHash, projectId)
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/wizard': (_, params) => {
            const wizardHash = params['hash']

            if (!wizardHash) {
                actions.setView('invalid')
            }

            actions.setWizardHash(wizardHash)

            const currentProjectId = values.currentProject?.id
            const projectCount = values.currentOrganization?.projects?.length || 0

            // Auto-select current project if available
            if (currentProjectId) {
                actions.setSelectedProject(currentProjectId)
            }

            // If there's only one project and we have a current project, skip selection
            if (projectCount <= 1 && currentProjectId) {
                actions.authenticateWizard(wizardHash, currentProjectId)
                actions.setView('pending')
            } else {
                actions.setView('project')
            }
        },
    })),
])
