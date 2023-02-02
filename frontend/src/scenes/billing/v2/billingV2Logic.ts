import { kea, path, actions, connect, reducers, afterMount, selectors, listeners } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { BillingProductV2Type, BillingV2Type, BillingVersion } from '~/types'
import { router } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urlToAction } from 'kea-router'
import { forms } from 'kea-forms'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from '@posthog/lemon-ui'
import { projectUsage } from './billing-utils'
import posthog from 'posthog-js'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'
import { pluralize } from 'lib/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import type { billingV2LogicType } from './billingV2LogicType'

export const ALLOCATION_THRESHOLD_ALERT = 0.85 // Threshold to show warning of event usage near limit
export const ALLOCATION_THRESHOLD_BLOCK = 1.2 // Threshold to block usage

export interface BillingAlertConfig {
    status: 'info' | 'warning' | 'error'
    title: string
    message: string
    contactSupport?: boolean
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

    data.free_trial_until = data.free_trial_until ? dayjs(data.free_trial_until) : undefined

    return data as BillingV2Type
}

export const billingV2Logic = kea<billingV2LogicType>([
    path(['scenes', 'billing', 'v2', 'billingLogic']),
    actions({
        setShowLicenseDirectInput: (show: boolean) => ({ show }),
        reportBillingAlertShown: (alertConfig: BillingAlertConfig) => ({ alertConfig }),
        reportBillingV2Shown: true,
        lockIfNecessary: true,
    }),
    connect({
        values: [featureFlagLogic, ['featureFlags'], preflightLogic, ['preflight']],
        actions: [userLogic, ['loadUser']],
    }),
    reducers({
        showLicenseDirectInput: [
            false,
            {
                setShowLicenseDirectInput: (_, { show }) => show,
            },
        ],
    }),
    loaders(() => ({
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
            (s) => [s.billing, s.preflight],
            (billing, preflight): BillingAlertConfig | undefined => {
                if (!billing || !preflight?.cloud) {
                    return
                }

                if (billing.free_trial_until && billing.free_trial_until.isAfter(dayjs())) {
                    const remainingDays = billing.free_trial_until.diff(dayjs(), 'days')
                    const remainingHours = billing.free_trial_until.diff(dayjs(), 'hours')

                    if (remainingHours > 72) {
                        return
                    }

                    return {
                        status: 'info',
                        title: `Your free trial will end in ${
                            remainingHours < 24 ? pluralize(remainingHours, 'hour') : pluralize(remainingDays, 'day')
                        }.`,
                        message: `Setup billing now to ensure you don't lose access to premium features.`,
                    }
                }

                if (billing.deactivated) {
                    return {
                        status: 'error',
                        title: 'Your organization has been temporarily suspended.',
                        message: 'Please contact support to reactivate it.',
                        contactSupport: true,
                    }
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
                        message: `You have currently used ${parseFloat(
                            (productApproachingLimit.percentage_usage * 100).toFixed(2)
                        )}% of your ${productApproachingLimit.type.toLowerCase()} allocation.`,
                    }
                }
            },
        ],
        isUserLocked: [
            (s) => [s.billing, s.preflight, s.billingVersion, s.featureFlags],
            (billing, preflight, billingVersion, featureFlags): boolean => {
                if (!billing || !preflight?.cloud) {
                    return false
                }
                // lock cloud users without a subscription out if they are above the usage limit on any product
                return Boolean(
                    ((billingVersion === 'v2' &&
                        !billing.has_active_subscription &&
                        !billing.free_trial_until &&
                        billing.products.find((x) => {
                            return x.percentage_usage > ALLOCATION_THRESHOLD_BLOCK
                        })) ||
                        billing.deactivated) &&
                        featureFlags[FEATURE_FLAGS.BILLING_LOCK_EVERYTHING]
                )
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
                    router.actions.replace('/organization/billing?success=true')
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

    listeners(({ actions, values }) => ({
        reportBillingV2Shown: () => {
            posthog.capture('billing v2 shown')
        },
        reportBillingAlertShown: ({ alertConfig }) => {
            posthog.capture('billing alert shown', {
                ...alertConfig,
            })
        },
        loadBillingSuccess: () => {
            if (
                router.values.location.pathname.includes('/organization/billing') &&
                router.values.searchParams['success']
            ) {
                // if the activation is successful, we reload the user to get the updated billing info on the organization
                actions.loadUser()
                router.actions.replace('/organization/billing')
            } else {
                actions.lockIfNecessary()
            }
        },

        lockIfNecessary: () => {
            if (values.isUserLocked && router.values.location.pathname !== '/organization/billing/locked') {
                posthog.capture('billing locked screen shown')
                router.actions.replace(urls.billingLocked())
            }
        },
        registerInstrumentationProps: async (_, breakpoint) => {
            await breakpoint(100)
            if (posthog && values.billing) {
                const payload = {
                    has_billing_plan: !!values.billing.has_active_subscription,
                    free_trial_until: values.billing.free_trial_until?.toISOString(),
                    customer_deactivated: values.billing.deactivated,
                    current_total_amount_usd: values.billing.current_total_amount_usd,
                }
                if (values.billing.custom_limits_usd) {
                    for (const product of Object.keys(values.billing.custom_limits_usd)) {
                        payload[`custom_limits_usd.${product}`] = values.billing.custom_limits_usd[product]
                    }
                }
                if (values.billing.products) {
                    for (const product of values.billing.products) {
                        const type = product.type.toLowerCase()
                        payload[`percentage_usage.${type}`] = product.percentage_usage
                        payload[`current_amount_usd.${type}`] = product.current_amount_usd
                        payload[`unit_amount_usd.${type}`] = product.unit_amount_usd
                        payload[`usage_limit.${type}`] = product.usage_limit
                        payload[`current_usage.${type}`] = product.current_usage
                        payload[`projected_usage.${type}`] = product.projected_usage
                        payload[`free_allocation.${type}`] = product.free_allocation
                    }
                }
                if (values.billing.billing_period) {
                    payload['billing_period_start'] = values.billing.billing_period.current_period_start
                    payload['billing_period_end'] = values.billing.billing_period.current_period_end
                }
                if (values.billing.license) {
                    payload['license_plan'] = values.billing.license.plan
                }
                posthog.register(payload)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadBilling()
    }),

    urlToAction(({ actions }) => ({
        // IMPORTANT: This needs to be above the "*" so it takes precedence
        '/organization/billing': (_params, _search, hash) => {
            if (hash.license) {
                actions.setShowLicenseDirectInput(true)
                actions.setActivateLicenseValues({ license: hash.license })
                actions.submitActivateLicense()
            }
        },
        '*': () => {
            actions.lockIfNecessary()
        },
    })),
])
