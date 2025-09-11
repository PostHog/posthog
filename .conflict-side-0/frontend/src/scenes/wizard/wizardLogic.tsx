import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'

import type { wizardLogicType } from './wizardLogicType'

export interface WizardTokenResponseType {
    success: boolean
}

export const wizardLogic = kea<wizardLogicType>([
    path(['scenes', 'wizard', 'wizardLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], projectLogic, ['currentProject']],
    })),
    actions({
        setWizardHash: (wizardHash: string | null) => ({ wizardHash }),
        setView: (view: 'project' | 'pending' | 'success' | 'invalid') => ({ view }),
        setSelectedProjectId: (projectId: number | null) => ({ projectId }),
        authenticateWizard: (wizardHash: string, projectId: number) => ({ wizardHash, projectId }),
        continueToAuthentication: () => ({}),
        handleWizardRouting: () => ({}),
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
                setSelectedProjectId: (_, { projectId }) => projectId,
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
                actions.setView('invalid')
                return
            }

            actions.setView('pending')
            actions.authenticateWizard(wizardHash, projectId)
        },
        handleWizardRouting: () => {
            const wizardHash = values.wizardHash

            if (!wizardHash) {
                actions.setView('invalid')
                return
            }

            // If we have a current project, auto-select it
            const currentProjectId = values.currentProject?.id
            if (currentProjectId) {
                actions.setSelectedProjectId(currentProjectId)
            }

            // If there's only one project, skip selection and authenticate
            if (values.availableProjects.length <= 1 && currentProjectId) {
                actions.authenticateWizard(wizardHash, currentProjectId)
                actions.setView('pending')
            } else {
                actions.setView('project')
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '/wizard': (_, params) => {
            const wizardHash = params['hash']
            actions.setWizardHash(wizardHash ?? null)
            actions.handleWizardRouting()
        },
    })),
])
