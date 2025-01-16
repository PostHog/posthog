import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS, UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { BillingProductV2AddonType } from '~/types'

import { billingProductLogic } from './billingProductLogic'
import type { downgradeLogicType } from './downgradeLogicType'

export interface ShowDowngradeModalPayload {
    addon: BillingProductV2AddonType
}

export const downgradeLogic = kea<downgradeLogicType>([
    path(['scenes', 'billing', 'downgradeLogic']),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    actions({
        showDowngradeModal: (payload: ShowDowngradeModalPayload) => ({ payload }),
        hideDowngradeModal: true,
        handleDowngrade: true,
    }),

    reducers({
        isDowngradeModalOpen: [
            false,
            {
                showDowngradeModal: () => true,
                hideDowngradeModal: () => false,
            },
        ],
        currentAddon: [
            null as BillingProductV2AddonType | null,
            {
                showDowngradeModal: (_, { payload }) => payload.addon,
                hideDowngradeModal: () => null,
            },
        ],
    }),

    selectors({
        isUserInExperiment: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => {
                return featureFlags[FEATURE_FLAGS.TEAMS_DOWNGRADE_FLOW] === 'test'
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        handleDowngrade: async () => {
            if (values.currentAddon) {
                const logic = billingProductLogic({ product: values.currentAddon })
                logic.actions.setSurveyResponse('$survey_response_1', values.currentAddon.type)
                logic.actions.reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, values.currentAddon.type)
            }
            actions.hideDowngradeModal()
        },
    })),
])
