import { lemonToast, Link } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api, { getJSONOrNull } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LemonButtonPropsBase } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import posthog from 'posthog-js'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { BillingProductV2Type, BillingV2PlanType, BillingV2Type, ProductKey } from '~/types'

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

export enum BillingAPIErrorCodes {
    OPEN_INVOICES_ERROR = 'open_invoices_error',
    NO_ACTIVE_PAYMENT_METHOD_ERROR = 'no_active_payment_method_error',
    COULD_NOT_PAY_INVOICES_ERROR = 'could_not_pay_invoices_error',
}

export interface UnsubscribeError {
    detail: string | JSX.Element
    link: JSX.Element
}

export interface BillingError {
    status: 'info' | 'warning' | 'error'
    message: string
    action: LemonButtonPropsBase
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
        setUnsubscribeError: (error: null | UnsubscribeError) => ({ error }),
        resetUnsubscribeError: true,
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
        unsubscribeError: [
            null as null | UnsubscribeError,
            {
                resetUnsubscribeError: () => null,
                setUnsubscribeError: (_, { error }) => error,
            },
        ],
        timeRemainingInSeconds: [
            0,
            {
                loadBillingSuccess: (_, { billing }) => {
                    if (!billing?.billing_period) {
                        return 0
                    }
                    const currentTime = dayjs()
                    const periodEnd = dayjs(billing.billing_period.current_period_end)
                    return periodEnd.diff(currentTime, 'second')
                },
            },
        ],
        timeTotalInSeconds: [
            0,
            {
                loadBillingSuccess: (_, { billing }) => {
                    if (!billing?.billing_period) {
                        return 0
                    }
                    const periodStart = dayjs(billing.billing_period.current_period_start)
                    const periodEnd = dayjs(billing.billing_period.current_period_end)
                    return periodEnd.diff(periodStart, 'second')
                },
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        billing: [
            null as BillingV2Type | null,
            {
                loadBilling: async () => {
                    const response = await api.get('api/billing')

                    return parseBillingResponse(response)
                },

                updateBillingLimits: async (limits: { [key: string]: string | null }) => {
                    const response = await api.update('api/billing', { custom_limits_usd: limits })

                    lemonToast.success('Billing limits updated')
                    return parseBillingResponse(response)
                },

                deactivateProduct: async (key: string) => {
                    actions.resetUnsubscribeError()
                    try {
                        const response = await api.getResponse('api/billing/deactivate?products=' + key)
                        const jsonRes = await getJSONOrNull(response)
                        lemonToast.success('You have been unsubscribed')
                        actions.reportProductUnsubscribed(key)
                        return parseBillingResponse(jsonRes)
                    } catch (error: any) {
                        if (error.code) {
                            if (error.code === BillingAPIErrorCodes.OPEN_INVOICES_ERROR) {
                                actions.setUnsubscribeError({
                                    detail: error.detail,
                                    link: (
                                        <Link to={values.billing?.stripe_portal_url} target="_blank">
                                            View invoices
                                        </Link>
                                    ),
                                } as UnsubscribeError)
                            } else if (error.code === BillingAPIErrorCodes.NO_ACTIVE_PAYMENT_METHOD_ERROR) {
                                actions.setUnsubscribeError({
                                    detail: error.detail,
                                } as UnsubscribeError)
                            } else if (error.code === BillingAPIErrorCodes.COULD_NOT_PAY_INVOICES_ERROR) {
                                actions.setUnsubscribeError({
                                    detail: error.detail,
                                    link: (
                                        <Link to={error.link || values.billing?.stripe_portal_url} target="_blank">
                                            {error.link ? 'View invoice' : 'View invoices'}
                                        </Link>
                                    ),
                                } as UnsubscribeError)
                            }
                        } else {
                            actions.setUnsubscribeError({
                                detail:
                                    typeof error.detail === 'string'
                                        ? error.detail
                                        : `We encountered a problem. Please try again or submit a support ticket.`,
                            } as UnsubscribeError)
                        }
                        console.error(error)
                        // This is a bit of a hack to prevent the page from re-rendering.
                        return values.billing
                    }
                },
            },
        ],
        billingError: [
            null as BillingError | null,
            {
                getInvoices: async () => {
                    // First check to see if there are open invoices
                    try {
                        const res = await api.getResponse('api/billing/get_invoices?status=open')
                        const jsonRes = await getJSONOrNull(res)
                        const numOpenInvoices = jsonRes['count']
                        if (numOpenInvoices > 0) {
                            const viewInvoicesButton = {
                                to:
                                    numOpenInvoices == 1 && jsonRes['link']
                                        ? jsonRes['link']
                                        : values.billing?.stripe_portal_url,
                                children: `View invoice${numOpenInvoices > 1 ? 's' : ''}`,
                                targetBlank: true,
                            }
                            return {
                                status: 'warning',
                                message: `You have ${numOpenInvoices} open invoice${
                                    numOpenInvoices > 1 ? 's' : ''
                                }. Please pay ${
                                    numOpenInvoices > 1 ? 'them' : 'it'
                                } before adding items to your subscription.`,
                                action: viewInvoicesButton,
                            }
                        }
                    } catch (error: any) {
                        console.error(error)
                    }
                    return null
                },
            },
        ],
        products: [
            [] as BillingProductV2Type[],
            {
                loadProducts: async () => {
                    const response = await api.get('api/billing/available_products')
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
        projectedTotalAmountUsdWithBillingLimits: [
            (s) => [s.billing],
            (billing: BillingV2Type): number => {
                if (!billing) {
                    return 0
                }
                let projectedTotal = 0
                for (const product of billing.products || []) {
                    const billingLimit: string =
                        billing?.custom_limits_usd?.[product.type] ||
                        (product.usage_key ? billing?.custom_limits_usd?.[product.usage_key] || '0' : '0')
                    projectedTotal += Math.min(
                        parseFloat(product.projected_amount_usd || '0'),
                        parseFloat(billingLimit)
                    )
                }
                return projectedTotal
            },
        ],
        over20kAnnual: [
            (s) => [s.billing, s.preflight, s.projectedTotalAmountUsdWithBillingLimits],
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
                return false
            },
        ],
        isAnnualPlan: [
            (s) => [s.billing],
            (billing) => {
                return billing?.billing_period?.interval === 'year'
            },
        ],
        supportPlans: [
            (s) => [s.billing],
            (billing: BillingV2Type): BillingV2PlanType[] => {
                const platformAndSupportProduct = billing?.products?.find(
                    (product) => product.type == ProductKey.PLATFORM_AND_SUPPORT
                )
                if (!platformAndSupportProduct?.plans) {
                    return []
                }

                const addonPlans = platformAndSupportProduct?.addons?.map((addon) => addon.plans).flat()
                const insertionIndex = Math.max(0, (platformAndSupportProduct?.plans?.length ?? 1) - 1)
                const allPlans = platformAndSupportProduct?.plans?.slice(0) || []
                allPlans.splice(insertionIndex, 0, ...addonPlans)
                return allPlans
            },
        ],
        hasSupportAddonPlan: [
            (s) => [s.billing],
            (billing: BillingV2Type): boolean => {
                return !!billing?.products
                    ?.find((product) => product.type == ProductKey.PLATFORM_AND_SUPPORT)
                    ?.addons.find((addon) => addon.plans.find((plan) => plan.current_plan))
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
                    await api.update('api/billing/license', {
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

            if (!values.billing || !values.preflight?.cloud) {
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
        actions.getInvoices()
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
