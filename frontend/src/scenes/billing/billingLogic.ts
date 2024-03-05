import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import posthog from 'posthog-js'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { BillingProductV2Type, BillingV2Type, ProductKey } from '~/types'

import type { billingLogicType } from './billingLogicType'

export const ALLOCATION_THRESHOLD_ALERT = 0.85 // Threshold to show warning of event usage near limit
export const ALLOCATION_THRESHOLD_BLOCK = 1.2 // Threshold to block usage

export interface BillingAlertConfig {
    status: 'info' | 'warning' | 'error'
    title: string
    message?: string
    contactSupport?: boolean
    buttonCTA?: string
    dismissKey?: string
    action?: LemonBannerAction
    pathName?: string
    onClose?: () => void
}

const parseBillingResponse = (data: Partial<BillingV2Type>): BillingV2Type => {
    if (data.billing_period) {
        data.billing_period = {
            current_period_start: dayjs(data.billing_period.current_period_start),
            current_period_end: dayjs(data.billing_period.current_period_end),
            interval: data.billing_period.interval,
        }
    }

    data.free_trial_until = data.free_trial_until ? dayjs(data.free_trial_until) : undefined
    data.amount_off_expires_at = data.amount_off_expires_at ? dayjs(data.amount_off_expires_at) : undefined
    // If expiration is in the middle of the current period, we let it expire at the end of the period
    if (
        data.amount_off_expires_at &&
        data.billing_period &&
        data.amount_off_expires_at.isBefore(data.billing_period.current_period_end) &&
        data.amount_off_expires_at.isAfter(data.billing_period.current_period_start)
    ) {
        data.amount_off_expires_at = data.billing_period.current_period_end
    }

    return data as BillingV2Type
}

export const billingLogic = kea<billingLogicType>([
    path(['scenes', 'billing', 'billingLogic']),
    actions({
        setProductSpecificAlert: (productSpecificAlert: BillingAlertConfig | null) => ({ productSpecificAlert }),
        setScrollToProductKey: (scrollToProductKey: ProductKey | null) => ({ scrollToProductKey }),
        setShowLicenseDirectInput: (show: boolean) => ({ show }),
        reportBillingAlertShown: (alertConfig: BillingAlertConfig) => ({ alertConfig }),
        reportBillingAlertActionClicked: (alertConfig: BillingAlertConfig) => ({ alertConfig }),
        reportBillingV2Shown: true,
        registerInstrumentationProps: true,
        setRedirectPath: true,
        setIsOnboarding: true,
        determineBillingAlert: true,
        setBillingAlert: (billingAlert: BillingAlertConfig | null) => ({ billingAlert }),
    }),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], preflightLogic, ['preflight']],
        actions: [
            userLogic,
            ['loadUser'],
            eventUsageLogic,
            ['reportProductUnsubscribed'],
            lemonBannerLogic({ dismissKey: 'usage-limit-exceeded' }),
            ['resetDismissKey as resetUsageLimitExceededKey'],
            lemonBannerLogic({ dismissKey: 'usage-limit-approaching' }),
            ['resetDismissKey as resetUsageLimitApproachingKey'],
        ],
    })),
    reducers({
        billingAlert: [
            null as BillingAlertConfig | null,
            {
                setBillingAlert: (_, { billingAlert }) => billingAlert,
            },
        ],
        scrollToProductKey: [
            null as ProductKey | null,
            {
                setScrollToProductKey: (_, { scrollToProductKey }) => scrollToProductKey,
            },
        ],
        productSpecificAlert: [
            null as BillingAlertConfig | null,
            {
                setProductSpecificAlert: (_, { productSpecificAlert }) => productSpecificAlert,
            },
        ],
        showLicenseDirectInput: [
            false,
            {
                setShowLicenseDirectInput: (_, { show }) => show,
            },
        ],
        redirectPath: [
            '' as string,
            {
                setRedirectPath: () => {
                    return window.location.pathname.includes('/onboarding')
                        ? window.location.pathname + window.location.search
                        : ''
                },
            },
        ],
        isOnboarding: [
            false,
            {
                setIsOnboarding: () => window.location.pathname.includes('/onboarding'),
            },
        ],
    }),
    loaders(({ actions }) => ({
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

                deactivateProduct: async (key: string) => {
                    const response = await api.get('api/billing-v2/deactivate?products=' + key)
                    lemonToast.success('Product unsubscribed')
                    actions.reportProductUnsubscribed(key)
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
        upgradeLink: [(s) => [s.preflight], (): string => '/organization/billing'],
        isUnlicensedDebug: [
            (s) => [s.preflight, s.billing],
            (preflight, billing): boolean => !!preflight?.is_debug && !billing?.billing_period,
        ],
        projectedTotalAmountUsd: [
            (s) => [s.billing],
            (billing: BillingV2Type): number => {
                if (!billing) {
                    return 0
                }
                let projectedTotal = 0
                for (const product of billing.products || []) {
                    projectedTotal += parseFloat(product.projected_amount_usd || '0')
                }
                return projectedTotal
            },
        ],
        over20kAnnual: [
            (s) => [s.billing, s.preflight, s.projectedTotalAmountUsd],
            (billing, preflight, projectedTotalAmountUsd) => {
                if (!billing || !preflight?.cloud) {
                    return
                }
                if (
                    billing.current_total_amount_usd_after_discount &&
                    (parseFloat(billing.current_total_amount_usd_after_discount) > 1666 ||
                        projectedTotalAmountUsd > 1666) &&
                    billing.billing_period?.interval === 'month'
                ) {
                    return true
                }
                return
            },
        ],
        isAnnualPlan: [
            (s) => [s.billing],
            (billing) => {
                return billing?.billing_period?.interval === 'year'
            },
        ],
    }),
    forms(({ actions, values }) => ({
        activateLicense: {
            defaults: { license: '' } as { license: string },
            errors: ({ license }) => ({
                license: !license ? 'Please enter your license key' : undefined,
            }),
            submit: async ({ license }, breakpoint) => {
                await breakpoint(500)
                try {
                    await api.update('api/billing-v2/license', {
                        license,
                    })

                    // Reset the URL so we don't trigger the license submission again
                    router.actions.replace(
                        `/${values.isOnboarding ? 'ingestion' : 'organization'}/billing?success=true`
                    )
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
        reportBillingAlertActionClicked: ({ alertConfig }) => {
            posthog.capture('billing alert action clicked', {
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
            }
            actions.registerInstrumentationProps()

            actions.determineBillingAlert()
        },
        determineBillingAlert: () => {
            if (values.productSpecificAlert) {
                actions.setBillingAlert(values.productSpecificAlert)
                return
            }

            if (!values.billing || !preflight?.cloud) {
                return
            }

            if (values.billing.free_trial_until && values.billing.free_trial_until.isAfter(dayjs())) {
                const remainingDays = values.billing.free_trial_until.diff(dayjs(), 'days')
                const remainingHours = values.billing.free_trial_until.diff(dayjs(), 'hours')

                if (remainingHours > 72) {
                    return
                }

                actions.setBillingAlert({
                    status: 'info',
                    title: `Your free trial will end in ${
                        remainingHours < 24 ? pluralize(remainingHours, 'hour') : pluralize(remainingDays, 'day')
                    }.`,
                    message: `Setup billing now to ensure you don't lose access to premium features.`,
                })
                return
            }

            if (values.billing.deactivated) {
                actions.setBillingAlert({
                    status: 'error',
                    title: 'Your organization has been temporarily suspended.',
                    message: 'Please contact support to reactivate it.',
                    contactSupport: true,
                })
                return
            }

            const productOverLimit = values.billing.products?.find((x: BillingProductV2Type) => {
                return x.percentage_usage > 1 && x.usage_key
            })

            if (productOverLimit) {
                actions.setBillingAlert({
                    status: 'error',
                    title: 'Usage limit exceeded',
                    message: `You have exceeded the usage limit for ${productOverLimit.name}. Please 
                        ${productOverLimit.subscribed ? 'increase your billing limit' : 'upgrade your plan'}
                        or data loss may occur.`,
                    dismissKey: 'usage-limit-exceeded',
                })
                return
            }

            actions.resetUsageLimitExceededKey()

            const productApproachingLimit = values.billing.products?.find(
                (x) => x.percentage_usage > ALLOCATION_THRESHOLD_ALERT
            )

            if (productApproachingLimit) {
                actions.setBillingAlert({
                    status: 'info',
                    title: 'You will soon hit your usage limit',
                    message: `You have currently used ${parseFloat(
                        (productApproachingLimit.percentage_usage * 100).toFixed(2)
                    )}% of your ${
                        productApproachingLimit.usage_key && productApproachingLimit.usage_key.toLowerCase()
                    } allocation.`,
                    dismissKey: 'usage-limit-approaching',
                })
                return
            }

            actions.resetUsageLimitApproachingKey()
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
                posthog.register(payload)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBilling()
    }),
    urlToAction(({ actions }) => ({
        // IMPORTANT: This needs to be above the "*" so it takes precedence
        '/*/billing': (_params, _search, hash) => {
            if (hash.license) {
                actions.setShowLicenseDirectInput(true)
                actions.setActivateLicenseValues({ license: hash.license })
                actions.submitActivateLicense()
            }
            if (_search.products) {
                const products = _search.products.split(',')
                actions.setScrollToProductKey(products[0])
            }
            actions.setRedirectPath()
            actions.setIsOnboarding()
        },
        '*': () => {
            actions.setRedirectPath()
            actions.setIsOnboarding()
        },
    })),
])
