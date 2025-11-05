import { afterMount, connect, kea, listeners, path } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { featureFlagConfirmationSettingsLogicType } from './featureFlagConfirmationSettingsLogicType'

export type ConfirmationMessageForm = {
    message: string
}

export const featureFlagConfirmationSettingsLogic = kea<featureFlagConfirmationSettingsLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagConfirmationSettingsLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam', 'loadCurrentTeamSuccess', 'updateCurrentTeamSuccess']],
    })),

    loaders(() => ({
        confirmationMessage: {
            __default: null as string | null,
            updateConfirmationMessage: async (data: ConfirmationMessageForm) => {
                await teamLogic.asyncActions.updateCurrentTeam({
                    feature_flag_confirmation_message: data.message,
                })
                lemonToast.success('Confirmation message saved')
                return data.message
            },
        },
    })),

    // isSubmitting is automatically handled by the kea-loaders
    // Use confirmationMessageLoading instead

    forms(({ actions }) => ({
        confirmationMessageForm: {
            defaults: { message: '' } as ConfirmationMessageForm,
            submit: ({ message }) => {
                actions.updateConfirmationMessage({ message })
            },
        },
    })),

    listeners(({ actions }) => ({
        updateCurrentTeamSuccess: ({ currentTeam }) => {
            // Update form value when team data changes
            const message = currentTeam?.feature_flag_confirmation_message || ''
            actions.setConfirmationMessageFormValue('message', message)
        },
        loadCurrentTeamSuccess: ({ currentTeam }) => {
            // Initialize form when team loads
            const message = currentTeam?.feature_flag_confirmation_message || ''
            actions.setConfirmationMessageFormValue('message', message)
        },
    })),

    afterMount(({ actions, values }) => {
        // Initialize form with current team value if already loaded
        if (values.currentTeam) {
            const message = values.currentTeam.feature_flag_confirmation_message || ''
            actions.setConfirmationMessageFormValue('message', message)
        }
    }),
])
