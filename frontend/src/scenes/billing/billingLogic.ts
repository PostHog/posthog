import { kea } from 'kea'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'
import { billingLogicType } from './billingLogicType'
import { BillingSubscription, PlanInterface, UserType, FormattedNumber } from '~/types'

export const UTM_TAGS = 'utm_medium=in-product&utm_campaign=billing-management'
export const ALLOWANCE_THRESHOLD_ALERT = 0.85 // Threshold to show warning of event usage near limit

export const billingLogic = kea<billingLogicType<PlanInterface, BillingSubscription, UserType>>({
    actions: {
        setUrlPath: (urlPath) => ({ urlPath }),
    },
    reducers: {
        urlPath: [
            '',
            {
                setUrlPath: (_, { urlPath }) => urlPath,
            },
        ],
    },
    loaders: {
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
    },
    selectors: {
        allowance: [
            () => [userLogic.selectors.user],
            (user: UserType) =>
                user.billing?.plan ? user.billing?.plan.allowance : user?.billing?.no_plan_event_allocation,
        ],
        percentage: [
            (s) => [s.allowance, userLogic.selectors.user],
            (allowance: FormattedNumber | null | undefined, user: UserType) => {
                if (!allowance || !user.billing?.current_usage) {
                    return null
                }
                return Math.min(Math.round((user.billing.current_usage.value / allowance.value) * 100) / 100, 1)
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
        alertToShow: [
            (s) => [s.allowance, userLogic.selectors.user, s.urlPath],
            (
                allowance: FormattedNumber | null | undefined,
                user: UserType,
                urlPath: string
            ): 'setup_billing' | 'usage_near_limit' | undefined => {
                // Determines which billing alert/warning to show to the user (if any)

                // Priority 1: In-progress incomplete billing setup
                if (user?.billing?.should_setup_billing && user?.billing.subscription_url) {
                    return 'setup_billing'
                }

                // Priority 2: Event allowance near limit
                if (
                    urlPath !== '/organization/billing' &&
                    allowance &&
                    user.billing?.current_usage &&
                    user.billing.current_usage.value / allowance.value >= ALLOWANCE_THRESHOLD_ALERT
                ) {
                    return 'usage_near_limit'
                }
            },
        ],
    },
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
    urlToAction: ({ actions }) => ({
        '*': ({ _: urlPath }: { _: string }) => {
            actions.setUrlPath(urlPath)
        },
    }),
})
