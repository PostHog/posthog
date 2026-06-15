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

// Mirror the server-side OAuth authorization code expiry (`AUTHORIZATION_CODE_EXPIRE_SECONDS`,
// 5 minutes). Once it elapses the callback is dead, so we proactively surface a timed-out state
// instead of letting the user complete the flow into a failed authentication.
export const WIZARD_SESSION_TIMEOUT_MS = 5 * 60 * 1000

export type WizardView = 'project' | 'pending' | 'success' | 'invalid' | 'timed_out'

export const wizardLogic = kea<wizardLogicType>([
    path(['scenes', 'wizard', 'wizardLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], projectLogic, ['currentProject']],
    })),
    actions({
        setWizardHash: (wizardHash: string | null) => ({ wizardHash }),
        setView: (view: WizardView) => ({ view }),
        setSelectedProjectId: (projectId: number | null) => ({ projectId }),
        authenticateWizard: (wizardHash: string, projectId: number) => ({ wizardHash, projectId }),
        continueToAuthentication: () => ({}),
        handleWizardRouting: () => ({}),
        startSessionTimer: () => ({}),
        sessionTimedOut: () => ({}),
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
            'project' as WizardView,
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
    listeners(({ actions, values, cache }) => ({
        startSessionTimer: () => {
            // Store an absolute deadline so the timer survives the disposables plugin's
            // pause/resume on tab visibility — if the 5 minutes lapse while the tab is hidden,
            // setup recomputes a non-positive delay on return and fires immediately.
            cache.sessionDeadline = Date.now() + WIZARD_SESSION_TIMEOUT_MS
            cache.disposables.add(() => {
                const remainingMs = Math.max(0, (cache.sessionDeadline ?? 0) - Date.now())
                const timeoutId = setTimeout(() => actions.sessionTimedOut(), remainingMs)
                return () => clearTimeout(timeoutId)
            }, 'wizardSessionTimer')
        },
        sessionTimedOut: () => {
            cache.disposables.dispose('wizardSessionTimer')
            // Only interrupt while the user is still deciding — never clobber a completed flow.
            if (values.view === 'project') {
                actions.setView('timed_out')
            }
        },
        authenticateWizard: () => {
            // The user has acted (or we auto-authenticated); the waiting clock no longer applies.
            cache.disposables.dispose('wizardSessionTimer')
        },
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
                // User now has to pick a project — start the clock while they're away.
                actions.startSessionTimer()
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
