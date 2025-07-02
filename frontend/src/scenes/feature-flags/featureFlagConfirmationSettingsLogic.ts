import { afterMount, connect, kea, listeners, path, reducers } from 'kea'
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
        actions: [teamLogic, ['updateCurrentTeam']],
    })),

    reducers({
        isSubmitting: [
            false,
            {
                updateConfirmationMessage: () => true,
                updateConfirmationMessageSuccess: () => false,
                updateConfirmationMessageFailure: () => false,
            },
        ],
    }),

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

    forms(({ actions }) => ({
        confirmationMessageForm: {
            defaults: { message: '' } as ConfirmationMessageForm,
            submit: ({ message }) => {
                actions.updateConfirmationMessage({ message })
            },
        },
    })),

    listeners(({ actions, values }) => ({
        updateCurrentTeamSuccess: () => {
            // Update form value when team data changes
            if (values.currentTeam?.feature_flag_confirmation_message !== undefined) {
                actions.setConfirmationMessageFormValue('message', values.currentTeam.feature_flag_confirmation_message)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        // Initialize form with current team value
        if (values.currentTeam?.feature_flag_confirmation_message !== undefined) {
            actions.setConfirmationMessageFormValue('message', values.currentTeam.feature_flag_confirmation_message)
        }
    }),
])
