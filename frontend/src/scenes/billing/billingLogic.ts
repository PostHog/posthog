import { kea } from 'kea'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'
import { billingLogicType } from 'types/scenes/billing/billingLogicType'
import { BillingSubscription } from '~/types'

export const billingLogic = kea<billingLogicType>({
    loaders: () => ({
        plans: [
            [],
            {
                loadPlans: async () => {
                    return await api.get('plans?self_serve=1')
                },
            },
        ],
        billingSubscription: [
            null as BillingSubscription | null,
            {
                subscribe: async (plan) => {
                    return await api.create('billing/subscribe', { plan })
                },
            },
        ],
    }),
    selectors: () => ({
        percentage: [
            () => [userLogic.selectors.user],
            (user) => {
                if (!user?.billing?.current_usage || !user?.billing.plan || !user?.billing.plan.allowance) {
                    return null
                }
                return Math.round((user.billing.current_usage.value / user.billing.plan.allowance.value) * 100) / 100
            },
        ],
        strokeColor: [
            (selectors) => [selectors.percentage],
            (percentage) => {
                let color: string | Record<string, string> = '#1890FF'
                if (percentage === null || percentage === undefined) {
                    /* No event limit set */
                    color = {
                        from: '#1890FF',
                        to: '#52C41A',
                    }
                }

                if (percentage && percentage > 0.65 && percentage < 0.8) {
                    color = '#F7A501'
                }
                if (percentage && percentage > 0.8) {
                    color = '#F54E00'
                }
                return color
            },
        ],
    }),
})
