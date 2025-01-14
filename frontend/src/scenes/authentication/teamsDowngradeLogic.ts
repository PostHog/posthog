import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { BillingProductV2AddonType } from '~/types'

import type { teamsDowngradeLogicType } from './teamsDowngradeLogicType'

export interface TeamsDowngradeModalProps {
    onClose?: () => void
}

export const teamsDowngradeLogic = kea<teamsDowngradeLogicType>([
    path(['scenes', 'authentication', 'teamsDowngradeLogic']),
    connect({
        values: [organizationLogic, ['currentOrganization']],
    }),
    selectors({
        enforce2FA: [
            (s) => [s.currentOrganization],
            (currentOrganization) => currentOrganization?.enforce_2fa || false,
        ],
    }),
    actions({
        showTeamsDowngradeModal: (addon: BillingProductV2AddonType) => ({ addon }),
        hideTeamsDowngradeModal: true,
        handleTeamsDowngrade: true,
    }),

    reducers({
        isTeamsDowngradeModalOpen: [
            false,
            {
                showTeamsDowngradeModal: () => true,
                hideTeamsDowngradeModal: () => false,
            },
        ],
        currentAddon: [
            null as BillingProductV2AddonType | null,
            {
                showTeamsDowngradeModal: (_, { addon }) => addon,
                hideTeamsDowngradeModal: () => null,
            },
        ],
    }),

    listeners(({ values, actions }) => ({
        handleTeamsDowngrade: () => {
            if (values.currentAddon) {
                const logic = billingProductLogic({ product: values.currentAddon })
                logic.actions.setSurveyResponse('$survey_response_1', values.currentAddon.type)
                logic.actions.reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, values.currentAddon.type)
            }
            actions.hideTeamsDowngradeModal()
        },
    })),
])
