import { kea, key, path, props, selectors } from 'kea'

import { BillingProductV2AddonType } from '~/types'

import type { billingProductAddonLogicType } from './billingProductAddonLogicType'
import { BillingGaugeItemKind } from './types'

export interface BillingProductAddonLogicProps {
    addon: BillingProductV2AddonType
}

export const billingProductAddonLogic = kea<billingProductAddonLogicType>([
    path(['scenes', 'billing', 'billingProductAddonLogic']),
    props({} as BillingProductAddonLogicProps),
    key((props) => props.addon.type),

    selectors({
        gaugeItems: [
            (_, props) => [props.addon],
            (
                addon: BillingProductV2AddonType
            ): Array<{
                type: BillingGaugeItemKind
                text: string
                value: number
            }> => [
                {
                    type: BillingGaugeItemKind.FreeTier,
                    text: 'Free tier limit',
                    value: addon.tiers?.[0]?.up_to || 0,
                },
                {
                    type: BillingGaugeItemKind.CurrentUsage,
                    text: 'Current',
                    value: addon.current_usage ?? 0,
                },
            ],
        ],
    }),
])
