import { actions, kea, listeners, path, reducers } from 'kea'

import { BillingPlanType } from '~/types'

import type { confirmUpgradeModalLogicType } from './confirmUpgradeModalLogicType'

export const confirmUpgradeModalLogic = kea<confirmUpgradeModalLogicType>([
    path(['lib', 'components', 'ConfirmUpgradeModal', 'confirmUpgradeModalLogic']),
    actions({
        showConfirmUpgradeModal: (
            upgradePlan: BillingPlanType,
            confirmCallback: () => void,
            cancelCallback: () => void
        ) => ({
            upgradePlan,
            confirmCallback,
            cancelCallback,
        }),
        hideConfirmUpgradeModal: true,
        confirm: true,
        cancel: true,
    }),
    reducers({
        upgradePlan: [
            null as BillingPlanType | null,
            {
                showConfirmUpgradeModal: (_, { upgradePlan }) => upgradePlan,
                hideConfirmUpgradeModal: () => null,
            },
        ],
        confirmCallback: [
            null as (() => void) | null,
            {
                showConfirmUpgradeModal: (_, { confirmCallback }) => confirmCallback,
                hideConfirmUpgradeModal: () => null,
            },
        ],
        cancelCallback: [
            null as (() => void) | null,
            {
                showConfirmUpgradeModal: (_, { cancelCallback }) => cancelCallback,
                hideConfirmUpgradeModal: () => null,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        confirm: async (_, breakpoint) => {
            await breakpoint(100)
            if (values.confirmCallback) {
                values.confirmCallback()
            }
            actions.hideConfirmUpgradeModal()
        },
        cancel: async (_, breakpoint) => {
            await breakpoint(100)
            if (values.cancelCallback) {
                values.cancelCallback()
            }
            actions.hideConfirmUpgradeModal()
        },
    })),
])
