import { kea } from 'kea'
import api from 'lib/api'
import { billingLogicType } from './billingLogicType'
import { PlanInterface, BillingType } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import posthog from 'posthog-js'
import { Scene } from 'scenes/sceneTypes'
import { sceneLogic } from 'scenes/sceneLogic'

export const UTM_TAGS = 'utm_medium=in-product&utm_campaign=billing-management'
export const ALLOCATION_THRESHOLD_ALERT = 0.85 // Threshold to show warning of event usage near limit

export enum BillingAlertType {
    SetupBilling = 'setup_billing',
    UsageNearLimit = 'usage_near_limit',
}

export const billingLogic = kea<billingLogicType<BillingAlertType>>({
    actions: {
        registerInstrumentationProps: true,
    },
    loaders: ({ actions }) => ({
        billing: [
            null as BillingType | null,
            {
                loadBilling: async () => {
                    const response = await api.get('api/billing/')
                    if (!response?.plan) {
                        actions.loadPlans()
                    }
                    actions.registerInstrumentationProps()
                    return response as BillingType
                },
            },
        ],
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
            null as BillingType | null,
            {
                subscribe: async (plan) => {
                    return await api.create('billing/subscribe', { plan })
                },
            },
        ],
    }),
    selectors: {
        eventAllocation: [(s) => [s.billing], (billing: BillingType) => billing?.event_allocation],
        percentage: [
            (s) => [s.eventAllocation, s.billing],
            (eventAllocation: number | null, billing: BillingType) => {
                if (!eventAllocation || !billing?.current_usage) {
                    return null
                }
                return Math.min(Math.round((billing.current_usage / eventAllocation) * 100) / 100, 1)
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
            (s) => [s.eventAllocation, s.billing, sceneLogic.selectors.scene],
            (eventAllocation: number | null, billing: BillingType, scene: Scene): BillingAlertType | undefined => {
                // Determines which billing alert/warning to show to the user (if any)

                // Priority 1: In-progress incomplete billing setup
                if (billing?.should_setup_billing && billing?.subscription_url) {
                    return BillingAlertType.SetupBilling
                }

                // Priority 2: Event allowance near limit
                if (
                    scene !== Scene.Billing &&
                    eventAllocation &&
                    billing.current_usage &&
                    billing.current_usage / eventAllocation >= ALLOCATION_THRESHOLD_ALERT
                ) {
                    return BillingAlertType.UsageNearLimit
                }
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            if (preflightLogic.values.preflight?.cloud) {
                actions.loadBilling()
            }
        },
    }),
    listeners: ({ values }) => ({
        subscribeSuccess: ({ billingSubscription }) => {
            if (billingSubscription?.subscription_url) {
                window.location.href = billingSubscription.subscription_url
            }
        },
        registerInstrumentationProps: async (_, breakpoint) => {
            await breakpoint(100)
            if (posthog && values.billing) {
                posthog.register({
                    has_billing_plan: !!values.billing?.plan,
                    metered_billing: values.billing.plan?.is_metered_billing,
                    event_allocation: values.billing.event_allocation,
                    allocation_used:
                        values.billing.event_allocation && values.billing.current_usage !== null
                            ? values.billing.current_usage / values.billing.event_allocation
                            : undefined,
                })
            }
        },
    }),
})
