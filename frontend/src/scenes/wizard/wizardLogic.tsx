import { actions, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { wizardLogicType } from './wizardLogicType'

export interface WizardTokenResponseType {
    success: boolean
}

export const wizardLogic = kea<wizardLogicType>([
    path(['scenes', 'wizard', 'wizardLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        setWizardHash: (wizardHash: string | null) => ({ wizardHash }),
        setView: (view: 'pending' | 'creating' | 'success' | 'invalid') => ({ view }),
        authenticateWizard: (wizardHash: string) => ({ wizardHash }),
    }),
    loaders(({ actions }) => ({
        wizardToken: [
            null as WizardTokenResponseType | null,
            {
                authenticateWizard: async ({ wizardHash }: { wizardHash: string }) => {
                    try {
                        const response: WizardTokenResponseType = await api.wizard.authenticateWizard({
                            hash: wizardHash,
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
            'pending' as 'pending' | 'creating' | 'success' | 'invalid',
            {
                setView: (_, { view }) => view,
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        '/wizard': (_, params) => {
            const wizardHash = params['hash']
            if (wizardHash) {
                actions.setWizardHash(wizardHash)
                actions.setView('pending')
                actions.authenticateWizard(wizardHash)
            } else {
                actions.setView('invalid')
            }
        },
    })),
])
