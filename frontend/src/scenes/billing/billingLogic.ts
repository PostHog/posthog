import { kea } from 'kea'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'
import { billingLogicType } from './billingLogicType'
import { BillingSubscription, PlanInterface, UserType, FormattedNumber } from '~/types'
import { sceneLogic, Scene } from 'scenes/sceneLogic'

export const UTM_TAGS = 'utm_medium=in-product&utm_campaign=billing-management'
export const ALLOCATION_THRESHOLD_ALERT = 0.85 // Threshold to show warning of event usage near limit

export enum BillingAlertType {
    SetupBilling = 'setup_billing',
    UsageNearLimit = 'usage_near_limit',
}

export const billingLogic = kea<billingLogicType<PlanInterface, BillingSubscription, UserType, FormattedNumber>>({
    loaders: {
        plans: [
            [] as PlanInterface[],
            {
                loadPlans: async () => {
                    const response = await api.get('api/plans?self_serve=1')
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
        eventAllocation: [() => [userLogic.selectors.user], (user: UserType) => user.billing?.event_allocation],
        percentage: [
            (s) => [s.eventAllocation, userLogic.selectors.user],
            (eventAllocation: FormattedNumber | number | null | undefined, user: UserType) => {
                if (!eventAllocation || !user.billing?.current_usage) {
                    return null
                }
                // :TODO: Temporary support for legacy FormattedNumber
                const allocation = typeof eventAllocation === 'number' ? eventAllocation : eventAllocation.value
                const usage =
                    typeof user.billing.current_usage === 'number'
                        ? user.billing.current_usage
                        : user.billing.current_usage.value
                return Math.min(Math.round((usage / allocation) * 100) / 100, 1)
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
            (s) => [s.eventAllocation, userLogic.selectors.user, sceneLogic.selectors.scene],
            (
                eventAllocation: FormattedNumber | number | null | undefined,
                user: UserType,
                scene: Scene
            ): BillingAlertType | undefined => {
                // Determines which billing alert/warning to show to the user (if any)

                // Priority 1: In-progress incomplete billing setup
                if (user?.billing?.should_setup_billing && user?.billing.subscription_url) {
                    return BillingAlertType.SetupBilling
                }

                // Priority 2: Event allowance near limit
                // :TODO: Temporary support for legacy FormattedNumber
                const allocation = typeof eventAllocation === 'number' ? eventAllocation : eventAllocation?.value
                const usage =
                    typeof user?.billing?.current_usage === 'number'
                        ? user.billing.current_usage
                        : user?.billing?.current_usage?.value
                if (
                    scene !== Scene.Billing &&
                    allocation &&
                    usage &&
                    usage / allocation >= ALLOCATION_THRESHOLD_ALERT
                ) {
                    return BillingAlertType.UsageNearLimit
                }
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            const user = userLogic.values.user
            if (user?.is_multi_tenancy && !user?.billing?.plan) {
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
