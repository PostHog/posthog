import { kea, path, actions, connect, reducers, afterMount, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import type { billingLogicType } from './billingLogicType'
import { BillingProductV2Type, BillingV2Type, BillingVersion } from '~/types'
import { router } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urlToAction } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { forms } from 'kea-forms'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from '@posthog/lemon-ui'
import { projectUsage } from './billing-utils'

export const ALLOCATION_THRESHOLD_ALERT = 0.85 // Threshold to show warning of event usage near limit

export enum BillingAlertType {
    SetupBilling = 'setup_billing',
    UsageNearLimit = 'usage_near_limit',
    UsageLimitExceeded = 'usage_limit_exceeded',
    FreeUsageNearLimit = 'free_usage_near_limit',
}

export interface BillingAlertConfig {
    status: 'info' | 'warning' | 'error'
    title: string
    message: string
}

const parseBillingResponse = (data: Partial<BillingV2Type>): BillingV2Type => {
    if (data.billing_period) {
        data.billing_period = {
            current_period_start: dayjs(data.billing_period.current_period_start),
            current_period_end: dayjs(data.billing_period.current_period_end),
        }

        data.products?.forEach((x) => {
            x.projected_usage = projectUsage(x.current_usage, data.billing_period)
        })
    }

    return data as BillingV2Type
}

export const billingLogic = kea<billingLogicType>([
    path(['scenes', 'billing', 'v2', 'billingLogic']),
    actions({
        setShowLicenseDirectInput: (show: boolean) => ({ show }),
    }),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [eventUsageLogic, ['reportIngestionBillingCancelled']],
    }),
    reducers({
        showLicenseDirectInput: [
            false,
            {
                setShowLicenseDirectInput: (_, { show }) => show,
            },
        ],
    }),
    loaders(({}) => ({
        billing: [
            null as BillingV2Type | null,
            {
                loadBilling: async () => {
                    const response = await api.get('api/billing-v2')

                    return parseBillingResponse(response)
                },

                updateBillingLimits: async (limits: { [key: string]: string | null }) => {
                    const response = await api.update('api/billing-v2', { custom_limits_usd: limits })
                    lemonToast.success('Billing limits updated')
                    return parseBillingResponse(response)
                },
            },
        ],
        products: [
            [] as BillingProductV2Type[],
            {
                loadProducts: async () => {
                    const response = await api.get('api/billing-v2/available_products')
                    return response
                },
            },
        ],
    })),
    selectors({
        billingVersion: [
            (s) => [s.billing, s.billingLoading],
            (billing, billingLoading): BillingVersion | undefined =>
                !billingLoading || billing ? (billing ? 'v2' : 'v1') : undefined,
        ],

        billingAlert: [
            (s) => [s.billing],
            (billing): BillingAlertConfig | undefined => {
                if (!billing) {
                    return
                }
                const productOverLimit = billing.products.find((x) => {
                    return x.percentage_usage > 1
                })

                if (productOverLimit) {
                    return {
                        status: 'error',
                        title: 'Usage limit exceeded',
                        message: `You have exceeded the usage limit for ${productOverLimit.name}. Please upgrade your plan or data loss may occur.`,
                    }
                }

                const productApproachingLimit = billing.products.find(
                    (x) => x.percentage_usage > ALLOCATION_THRESHOLD_ALERT
                )

                if (productApproachingLimit) {
                    return {
                        status: 'info',
                        title: 'You will soon hit your usage limit',
                        message: `You have currently used ${(
                            productApproachingLimit.percentage_usage * 100
                        ).toPrecision(2)}% of your ${productApproachingLimit.type.toLowerCase()} allocation.`,
                    }
                }
            },
        ],
    }),
    forms(({ actions }) => ({
        activateLicense: {
            defaults: { license: '' } as { license: string },
            errors: ({ license }) => ({
                license: !license ? 'Please enter your license key' : undefined,
            }),
            submit: async ({ license }, breakpoint) => {
                breakpoint(500)
                try {
                    await api.update('api/billing-v2/license', {
                        license,
                    })

                    // Reset the URL so we don't trigger the license submission again
                    router.actions.replace('/organization/billing')
                    setTimeout(() => {
                        window.location.reload() // Permissions, projects etc will be out of date at this point, so refresh
                    }, 100)
                } catch (e: any) {
                    actions.setActivateLicenseManualErrors({
                        license: e.detail || 'License could not be activated. Please contact support.',
                    })
                    throw e
                }
            },
        },
    })),

    afterMount(({ actions }) => {
        actions.loadBilling()
    }),

    urlToAction(({ actions }) => ({
        '/organization/billing': (_params, _search, hash) => {
            if (hash.license) {
                actions.setShowLicenseDirectInput(true)
                actions.setActivateLicenseValues({ license: hash.license })
                actions.submitActivateLicense()
            }
        },
    })),
])
