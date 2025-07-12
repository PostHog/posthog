import { LemonDialog, lemonToast, Link } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { capitalizeFirstLetter, FieldNamePath, forms } from 'kea-forms'
import { lazyLoaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api, { getJSONOrNull } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LemonButtonPropsBase } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import posthog from 'posthog-js'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import {
    BillingPlan,
    BillingPlanType,
    BillingProductV2Type,
    BillingType,
    ProductKey,
    StartupProgramLabel,
} from '~/types'

import type { billingLogicType } from './billingLogicType'
import { DEFAULT_ESTIMATED_MONTHLY_CREDIT_AMOUNT_USD } from './CreditCTAHero'

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

const parseBillingResponse = (data: Partial<BillingType>): BillingType => {
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

    return data as BillingType
}

export const billingLogic = kea<billingLogicType>([
    path(['scenes', 'billing', 'billingLogic']),
    actions({
        setProductSpecificAlert: (productSpecificAlert: BillingAlertConfig | null) => ({ productSpecificAlert }),
        setScrollToProductKey: (scrollToProductKey: ProductKey | null) => ({ scrollToProductKey }),
        setShowLicenseDirectInput: (show: boolean) => ({ show }),
        reportBillingAlertShown: (alertConfig: BillingAlertConfig) => ({ alertConfig }),
        reportBillingAlertActionClicked: (alertConfig: BillingAlertConfig) => ({ alertConfig }),
        reportCreditsFormSubmitted: (creditInput: number) => ({ creditInput }),
        reportCreditsModalShown: true,
        reportBillingShown: true,
        registerInstrumentationProps: true,
        reportCreditsCTAShown: (creditOverview: any) => ({ creditOverview }),
        setRedirectPath: true,
        setIsOnboarding: true,
        determineBillingAlert: true,
        setUnsubscribeError: (error: null | UnsubscribeError) => ({ error }),
        resetUnsubscribeError: true,
        setBillingAlert: (billingAlert: BillingAlertConfig | null) => ({ billingAlert }),
        showPurchaseCreditsModal: (isOpen: boolean) => ({ isOpen }),
        toggleCreditCTAHeroDismissed: (isDismissed: boolean) => ({ isDismissed }),
        setComputedDiscount: (discount: number) => ({ discount }),
        scrollToProduct: (productType: string) => ({ productType }),
    }),
    connect({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['preflight'],
            organizationLogic,
            ['currentOrganization'],
        ],
        actions: [
            userLogic,
            ['loadUser'],
            organizationLogic,
            ['loadCurrentOrganization'],
            eventUsageLogic,
            ['reportProductUnsubscribed'],
            lemonBannerLogic({ dismissKey: 'usage-limit-exceeded' }),
            ['resetDismissKey as resetUsageLimitExceededKey'],
            lemonBannerLogic({ dismissKey: 'usage-limit-approaching' }),
            ['resetDismissKey as resetUsageLimitApproachingKey'],
        ],
    }),
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
        isPurchaseCreditsModalOpen: [
            false,
            {
                showPurchaseCreditsModal: (_, { isOpen }) => isOpen,
            },
        ],
        isCreditCTAHeroDismissed: [
            false,
            { persist: true },
            {
                toggleCreditCTAHeroDismissed: (_, { isDismissed }) => isDismissed,
            },
        ],
        computedDiscount: [
            0,
            {
                setComputedDiscount: (_, { discount }) => discount,
            },
        ],
    }),
    lazyLoaders(({ actions, values }) => ({
        billing: [
            null as BillingType | null,
            {
                loadBilling: async () => {
                    // Note: this is a temporary flag to skip forecasting in the billing page
                    // for customers running into performance issues until we have a more permanent fix
                    // of splitting the billing and forecasting data.
                    const skipForecasting = values.featureFlags[FEATURE_FLAGS.BILLING_SKIP_FORECASTING]
                    try {
                        const response = await api.get(
                            'api/billing' + (skipForecasting ? '?include_forecasting=false' : '')
                        )

                        return parseBillingResponse(response)
                    } catch (error: any) {
                        if (error.data?.code === 'no_license') {
                            return null
                        }
                        throw error
                    }
                },

                updateBillingLimits: async (limits: { [key: string]: number | null }) => {
                    try {
                        const response = await api.update('api/billing', { custom_limits_usd: limits })
                        lemonToast.success('Billing limits updated')
                        actions.loadBilling()
                        return parseBillingResponse(response)
                    } catch (error: any) {
                        lemonToast.error(
                            'There was an error updating your billing limits. Please try again or contact support.'
                        )
                        throw error
                    }
                },

                deactivateProduct: async (key: string, breakpoint) => {
                    // clear upgrade params from URL
                    // Note(@zach): This is not working properly. We need to look into this.
                    const currentURL = new URL(window.location.href)
                    currentURL.searchParams.delete('upgraded')
                    currentURL.searchParams.delete('products')
                    router.actions.push(currentURL.pathname + currentURL.search)

                    actions.resetUnsubscribeError()
                    try {
                        const response = await api.getResponse('api/billing/deactivate?products=' + key)
                        const jsonRes = await getJSONOrNull(response)

                        lemonToast.success(
                            "You have been unsubscribed. We're sad to see you go. May the hedgehogs be ever in your favor."
                        )
                        actions.reportProductUnsubscribed(key)

                        // Reload billing, user, and organization to get the updated available features
                        actions.loadBilling()
                        await breakpoint(2000) // Wait enough time for the organization to be updated
                        actions.loadUser()
                        actions.loadCurrentOrganization()

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
                loadInvoices: async () => {
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
        creditOverview: [
            {
                eligible: false,
                estimated_monthly_credit_amount_usd: DEFAULT_ESTIMATED_MONTHLY_CREDIT_AMOUNT_USD,
                status: 'none',
                invoice_url: null,
                collection_method: null,
                cc_last_four: null,
                email: null,
            },
            {
                loadCreditOverview: async () => {
                    // Check if the user is subscribed
                    if (values.billing?.has_active_subscription) {
                        const response = await api.get('api/billing/credits/overview')
                        if (!values.creditForm.creditInput) {
                            actions.setCreditFormValue(
                                'creditInput',
                                Math.round(
                                    (response.estimated_monthly_credit_amount_usd ||
                                        DEFAULT_ESTIMATED_MONTHLY_CREDIT_AMOUNT_USD) * 12
                                )
                            )
                        }

                        if (response.eligible && response.status === 'none') {
                            actions.reportCreditsCTAShown(response)
                        }
                        return response
                    }
                    // Return default values if not subscribed
                    return {
                        eligible: false,
                        estimated_monthly_credit_amount_usd: DEFAULT_ESTIMATED_MONTHLY_CREDIT_AMOUNT_USD,
                        status: 'none',
                        invoice_url: null,
                        collection_method: null,
                        cc_last_four: null,
                        email: null,
                    }
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
        supportPlans: [
            (s) => [s.billing],
            (billing: BillingType): BillingPlanType[] => {
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
            (billing: BillingType): boolean => {
                return !!billing?.products
                    ?.find((product) => product.type == ProductKey.PLATFORM_AND_SUPPORT)
                    ?.addons.find((addon) => addon.plans.find((plan) => plan.current_plan))
            },
        ],
        creditDiscount: [(s) => [s.computedDiscount], (computedDiscount) => computedDiscount || 0],
        billingPlan: [
            (s) => [s.billing],
            (billing: BillingType | null): BillingPlan | null => billing?.billing_plan || null,
        ],
        startupProgramLabelCurrent: [
            (s) => [s.billing],
            (billing: BillingType | null): StartupProgramLabel | null => billing?.startup_program_label || null,
        ],
        startupProgramLabelPrevious: [
            (s) => [s.billing],
            (billing: BillingType | null): StartupProgramLabel | null =>
                billing?.startup_program_label_previous || null,
        ],
        isAnnualPlanCustomer: [
            (s) => [s.billing],
            (billing: BillingType | null): boolean => billing?.is_annual_plan_customer || false,
        ],
        showBillingSummary: [
            (s) => [s.billing, s.isOnboarding],
            (billing: BillingType | null, isOnboarding: boolean): boolean => {
                return !isOnboarding && !!billing?.billing_period
            },
        ],
        showCreditCTAHero: [
            (s) => [s.creditOverview, s.featureFlags],
            (creditOverview, featureFlags): boolean => {
                const isEligible = creditOverview.eligible || !!featureFlags[FEATURE_FLAGS.SELF_SERVE_CREDIT_OVERRIDE]
                return isEligible && creditOverview.status !== 'paid'
            },
        ],
        showBillingHero: [
            (s) => [s.billing, s.billingPlan, s.showCreditCTAHero],
            (billing: BillingType | null, billingPlan: BillingPlan | null, showCreditCTAHero: boolean): boolean => {
                const platformAndSupportProduct = billing?.products?.find(
                    (product) => product.type === ProductKey.PLATFORM_AND_SUPPORT
                )
                return !!billingPlan && !billing?.trial && !!platformAndSupportProduct && !showCreditCTAHero
            },
        ],
        isManagedAccount: [
            (s) => [s.billing],
            (billing: BillingType): boolean => {
                return !!(billing?.account_owner?.name || billing?.account_owner?.email)
            },
        ],
        accountOwner: [
            (s) => [s.billing],
            (billing: BillingType): { name?: string; email?: string } | null => billing?.account_owner || null,
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
        creditForm: {
            defaults: {
                creditInput: '',
                collectionMethod: 'charge_automatically',
            },
            submit: async ({ creditInput, collectionMethod }) => {
                await api.create('api/billing/credits/purchase', {
                    annual_amount_usd: +Math.round(+creditInput - +creditInput * values.creditDiscount),
                    discount_percent: values.computedDiscount * 100,
                    collection_method: collectionMethod,
                })

                actions.showPurchaseCreditsModal(false)
                actions.loadCreditOverview()
                actions.reportCreditsFormSubmitted(+creditInput)

                LemonDialog.open({
                    title: 'Your credit purchase has been submitted',
                    width: 536,
                    content:
                        collectionMethod === 'send_invoice' ? (
                            <>
                                <p className="mb-4">
                                    The invoice for your credits has been created and it will be emailed to the email on
                                    file.
                                </p>
                                <p>
                                    Once the invoice is paid we will apply the credits to your account. Until the
                                    invoice is paid you will be charged for usage as normal.
                                </p>
                            </>
                        ) : (
                            <>
                                <p>
                                    Your card will be charged soon and the credits will be applied to your account.
                                    Please make sure your{' '}
                                    <Link to={values.billing?.stripe_portal_url} target="_blank">
                                        card on file
                                    </Link>{' '}
                                    is up to date. You will receive an email when the credits are applied.
                                </p>
                            </>
                        ),
                })
            },
            errors: ({ creditInput, collectionMethod }) => ({
                creditInput: !creditInput
                    ? 'Please enter the amount of credits you want to purchase'
                    : // This value is used because 3333 - 10% = 3000
                    +creditInput < 3333
                    ? 'Please enter a credit amount of at least $3,333'
                    : undefined,
                collectionMethod: !collectionMethod ? 'Please select a collection method' : undefined,
            }),
        },
    })),
    listeners(({ actions, values }) => ({
        reportBillingShown: () => {
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
        reportCreditsModalShown: () => {
            posthog.capture('credits modal shown')
        },
        reportCreditsFormSubmitted: ({ creditInput }) => {
            posthog.capture('credits modal credit form submitted', {
                credit_amount_usd: creditInput,
            })
        },
        reportCreditsCTAShown: ({ creditOverview }) => {
            posthog.capture('credits cta shown', {
                eligible: creditOverview.eligible,
                status: creditOverview.status,
                estimated_monthly_credit_amount_usd:
                    creditOverview.estimated_monthly_credit_amount_usd || DEFAULT_ESTIMATED_MONTHLY_CREDIT_AMOUNT_USD,
            })
        },
        toggleCreditCTAHeroDismissed: ({ isDismissed }) => {
            if (isDismissed) {
                posthog.capture('credits cta hero dismissed')
            }
        },
        loadBillingSuccess: async (_, breakpoint) => {
            actions.registerInstrumentationProps()
            actions.determineBillingAlert()
            actions.loadCreditOverview()

            // If the activation is successful, we reload the user/organization to get the updated available features
            // activation can be triggered from the billing page or onboarding
            if (
                (router.values.location.pathname.includes('/organization/billing') ||
                    router.values.location.pathname.includes('/onboarding')) &&
                (router.values.searchParams['success'] || router.values.searchParams['upgraded'])
            ) {
                // Wait enough time for the organization to be updated
                await breakpoint(1000)
                actions.loadUser()
                actions.loadCurrentOrganization()
                // Clear the params from the billing page so we don't trigger the activation again
                if (router.values.location.pathname.includes('/organization/billing')) {
                    router.actions.replace('/organization/billing')
                }
            }
        },
        determineBillingAlert: () => {
            // If we already have a billing alert, don't show another one
            if (values.billingAlert) {
                return
            }

            if (values.productSpecificAlert) {
                actions.setBillingAlert(values.productSpecificAlert)
                return
            }

            if (!values.billing || !values.preflight?.cloud) {
                return
            }

            const trial = values.billing.trial
            if (trial && trial.expires_at && dayjs(trial.expires_at).isAfter(dayjs())) {
                if (trial.type === 'autosubscribe' || trial.status !== 'active') {
                    // Only show for standard ones (managed by sales)
                    return
                }

                const remainingDays = dayjs(trial.expires_at).diff(dayjs(), 'days')
                const remainingHours = dayjs(trial.expires_at).diff(dayjs(), 'hours')
                if (remainingHours > 72) {
                    return
                }

                const contactEmail = values.billing.account_owner?.email || 'sales@posthog.com'
                const contactName = values.billing.account_owner?.name || 'sales'
                actions.setBillingAlert({
                    status: 'info',
                    title: `Your free trial for the ${capitalizeFirstLetter(trial.target)} plan will end in ${
                        remainingHours < 24 ? pluralize(remainingHours, 'hour') : pluralize(remainingDays, 'day')
                    }.`,
                    message: `If you have any questions, please reach out to ${contactName} at ${contactEmail}.`,
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
                const hideProductFlag = `billing_hide_product_${productOverLimit?.type}`
                const isHidden = values.featureFlags[hideProductFlag] === true
                if (isHidden) {
                    return
                }
                actions.setBillingAlert({
                    status: 'error',
                    title: 'Usage limit exceeded',
                    message: `You have exceeded the usage limit for ${productOverLimit.name}. Please 
                        ${productOverLimit.subscribed ? 'increase your billing limit' : 'upgrade your plan'}
                        or ${
                            productOverLimit.name === 'Data warehouse'
                                ? 'data will not be synced'
                                : productOverLimit.name === 'Feature flags & Experiments'
                                ? 'feature flags will not evaluate'
                                : 'data loss may occur'
                        }.`,
                    dismissKey: 'usage-limit-exceeded',
                })
                return
            }

            actions.resetUsageLimitExceededKey()

            const productApproachingLimit = values.billing.products?.find(
                (x) => x.percentage_usage > ALLOCATION_THRESHOLD_ALERT
            )

            if (productApproachingLimit) {
                const hideProductFlag = `billing_hide_product_${productApproachingLimit?.type}`
                const isHidden = values.featureFlags[hideProductFlag] === true
                if (isHidden) {
                    return
                }
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
        setCreditFormValue: ({ name, value }) => {
            if (name === 'creditInput' || (name as FieldNamePath)?.[0] === 'creditInput') {
                const spend = +value
                let discount = 0
                if (spend >= 100000) {
                    discount = 0.35
                } else if (spend >= 60000) {
                    discount = 0.25
                } else if (spend >= 20000) {
                    discount = 0.2
                } else if (spend >= 3000) {
                    discount = 0.1
                }
                actions.setComputedDiscount(discount)
            }
        },
        registerInstrumentationProps: async (_, breakpoint) => {
            await breakpoint(100)
            if (posthog && values.billing) {
                const payload: { [key: string]: any } = {
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
        showPurchaseCreditsModal: ({ isOpen }) => {
            if (isOpen) {
                actions.reportCreditsModalShown()
            }
        },
        scrollToProduct: ({ productType }) => {
            const element = document.querySelector(`[data-attr="billing-product-addon-${productType}"]`)
            element?.scrollIntoView({
                behavior: 'smooth',
                block: 'center',
            })
        },
    })),
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
            if (_search.billing_error) {
                actions.setBillingAlert({
                    status: 'error',
                    title: 'Error',
                    message: _search.billing_error,
                    contactSupport: true,
                })
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
