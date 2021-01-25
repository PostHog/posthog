import { kea } from 'kea'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'
import { billingLogicType } from './billingLogicType'
import { BillingSubscription, PlanInterface, UserType } from '~/types'

export const billingLogic = kea<billingLogicType<PlanInterface, BillingSubscription, UserType>>({
    loaders: () => ({
        plans: [
            [] as PlanInterface[],
            {
                loadPlans: async () => {
                    const response = await api.get('plans?self_serve=1')
                    return response.results
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
                let color: string | Record<string, string> = 'var(--primary)'
                if (percentage === null || percentage === undefined) {
                    /* No event limit set */
                    color = {
                        from: '#1890FF',
                        to: '#52C41A',
                    }
                }

                if (percentage && percentage > 0.65 && percentage < 0.8) {
                    color = 'var(--warning)'
                }
                if (percentage && percentage > 0.8) {
                    color = 'var(--danger)'
                }
                return color
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            const user = userLogic.values.user
            if (!user?.billing?.plan || user?.billing?.should_setup_billing) {
                actions.loadPlans()
            }
        },
    }),
    listeners: () => ({
        subscribeSuccess: ({ billingSubscription }) => {
            if (billingSubscription?.subscription_url) {
                window.location.href = billingSubscription.subscription_url
            }
        },
    }),
})
