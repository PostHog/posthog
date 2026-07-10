import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import type { wizardLogicType } from './wizardLogicType'

export interface WizardTokenResponseType {
    success: boolean
}

export const wizardLogic = kea<wizardLogicType>([
    path(['scenes', 'wizard', 'wizardLogic']),
    connect(() => ({
        values: [
            organizationLogic,
            ['currentOrganization'],
            projectLogic,
            ['currentProject'],
            userLogic,
            ['otherOrganizations'],
        ],
        actions: [userLogic, ['updateCurrentOrganization']],
    })),
    actions({
        setWizardHash: (wizardHash: string | null) => ({ wizardHash }),
        setView: (view: 'project' | 'pending' | 'success' | 'invalid') => ({ view }),
        setSelectedProjectId: (projectId: number | null) => ({ projectId }),
        authenticateWizard: (wizardHash: string, projectId: number) => ({ wizardHash, projectId }),
        continueToAuthentication: () => ({}),
        switchOrganization: (organizationId: string) => ({ organizationId }),
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
        availableOrganizations: [
            (s) => [s.currentOrganization, s.otherOrganizations],
            (currentOrganization, otherOrganizations) => {
                const organizations = []

                if (currentOrganization) {
                    organizations.push({ value: currentOrganization.id, label: currentOrganization.name })
                }

                for (const organization of otherOrganizations) {
                    organizations.push({ value: organization.id, label: organization.name })
                }

                return organizations
            },
        ],
        currentOrganizationId: [
            (s) => [s.currentOrganization],
            (currentOrganization) => currentOrganization?.id ?? null,
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
        switchOrganization: ({ organizationId }) => {
            const wizardHash = values.wizardHash

            if (!wizardHash || organizationId === values.currentOrganizationId) {
                return
            }

            // Switching org requires a reload to load that org's projects. Preserve the wizard
            // hash in the destination so the flow resumes where it left off in the new org.
            actions.updateCurrentOrganization(organizationId, `/wizard?hash=${wizardHash}`)
        },
        handleWizardRouting: () => {
            const wizardHash = values.wizardHash

            if (!wizardHash) {
                actions.setView('invalid')
                return
            }

            // Pre-select the current project for convenience, but never auto-authenticate:
            // always make the user confirm which project their events will be attached to,
            // even when there's only one candidate.
            const currentProjectId = values.currentProject?.id
            if (currentProjectId) {
                actions.setSelectedProjectId(currentProjectId)
            }

            actions.setView('project')
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
