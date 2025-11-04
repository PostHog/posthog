import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconArrowRight, IconCheck } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { urls } from 'scenes/urls'

import { BillingProductV2Type, ProductKey } from '~/types'

import { CampaignConfig } from './campaigns/lenny'
import { couponLogic } from './couponLogic'

interface CouponRedemptionProps {
    campaign: string
    config: CampaignConfig
    requiresBilling?: boolean
}

const BillingUpgradeCTAWrapper: React.FC<{ platformAndSupportProduct: BillingProductV2Type }> = ({
    platformAndSupportProduct,
}) => {
    const { billing } = useValues(billingLogic)
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)
    const { billingProductLoading } = useValues(billingProductLogic({ product: platformAndSupportProduct }))
    return (
        <BillingUpgradeCTA
            type="primary"
            disableClientSideRouting
            loading={!!billingProductLoading}
            onClick={() => startPaymentEntryFlow(platformAndSupportProduct, window.location.pathname)}
        >
            {billing?.customer_id ? 'Subscribe' : 'Add billing details'}
        </BillingUpgradeCTA>
    )
}

export function CouponRedemption({ campaign, config, requiresBilling = true }: CouponRedemptionProps): JSX.Element {
    const logic = couponLogic({ campaign })
    const { claimed, claimedDetails, isAdminOrOwner } = useValues(logic)
    const { billing, billingLoading } = useValues(billingLogic)

    const platformAndSupportProduct = billing?.products?.find(
        (product) => product.type === ProductKey.PLATFORM_AND_SUPPORT
    )

    if (!isAdminOrOwner) {
        return (
            <div className="mx-auto max-w-200 mt-6 px-4">
                <LemonBanner type="warning">
                    <h2 className="mb-2">Admin or owner permission required</h2>
                    <p>
                        You need to be an organization admin or owner to claim coupons. Please contact your organization
                        admin for assistance.
                    </p>
                    <LemonButton type="primary" to={urls.projectHomepage()} className="mt-2">
                        Return to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    return (
        <div className="mx-auto max-w-[1200px]">
            {/* Hero section */}
            <div className="flex flex-col items-center mb-8 mt-8">
                {config.HeroImage && <config.HeroImage className="h-auto w-full max-w-100 mb-4" />}
                <div className="text-center">
                    <h2 className="text-2xl sm:text-3xl font-bold mb-2">{config.heroTitle}</h2>
                    <h3 className="text-base sm:text-lg text-muted">{config.heroSubtitle}</h3>
                </div>
            </div>

            <div className="grid md:grid-cols-2 gap-8 mb-8">
                {/* Left: Benefits & Eligibility */}
                <div className="space-y-6">
                    <div className="bg-surface-secondary rounded-lg p-6">
                        <h2 className="text-xl mb-4">What you'll get</h2>
                        <div className="space-y-3">
                            {config.benefits.map((benefit, index) => (
                                <div key={index} className="flex items-start">
                                    <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                                    <div>
                                        <h4 className="font-semibold">{benefit.title}</h4>
                                        <p className="text-muted text-sm">{benefit.description}</p>
                                    </div>
                                </div>
                            ))}
                        </div>
                        {config.footerNote && <div className="mt-6 text-sm text-muted">{config.footerNote}</div>}
                    </div>

                    {config.eligibilityCriteria && config.eligibilityCriteria.length > 0 && (
                        <div className="bg-surface-secondary rounded-lg p-6">
                            <h2 className="text-xl mb-4">Eligibility</h2>
                            <ul className="space-y-2">
                                {config.eligibilityCriteria.map((criterion, index) => (
                                    <li key={index} className="flex items-start">
                                        <IconArrowRight className="text-muted shrink-0 mt-1 mr-2" />
                                        <span className="text-sm">{criterion}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>

                {/* Right: Steps */}
                <div className="space-y-4">
                    {/* Step 1: Add billing details (conditional) */}
                    {requiresBilling && (
                        <div className="bg-surface-secondary rounded-lg p-6">
                            <h2 className="text-xl mb-4">Step 1: Add billing details</h2>
                            {billingLoading ? (
                                <div className="flex items-center gap-2">
                                    <Spinner className="text-lg" />
                                    <span>Checking if you're on a paid plan</span>
                                </div>
                            ) : billing?.has_active_subscription ? (
                                <div className="flex items-center gap-2 text-success">
                                    <IconCheck className="shrink-0" />
                                    <span>You're on a paid plan</span>
                                </div>
                            ) : (
                                <div className="flex flex-col items-start gap-2">
                                    <p className="text-muted mb-2">
                                        To claim this coupon, you need to be on a paid plan.
                                    </p>
                                    <p className="text-muted mb-2">
                                        Don't worry - you'll only pay for what you use and can set billing limits as low
                                        as $0 to control your spend.
                                    </p>
                                    <p className="text-muted mb-2 italic">
                                        P.S. You still keep the monthly free allowance for every product!
                                    </p>
                                    {platformAndSupportProduct && (
                                        <BillingUpgradeCTAWrapper
                                            platformAndSupportProduct={platformAndSupportProduct}
                                        />
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Step 2: Redeem coupon */}
                    <div className="bg-surface-secondary rounded-lg p-6">
                        <h2 className="text-xl mb-4">{requiresBilling ? 'Step 2: ' : ''}Redeem your coupon</h2>

                        {claimed ? (
                            <div className="space-y-4">
                                <div className="flex items-center gap-2 text-success">
                                    <IconCheck className="shrink-0" />
                                    <span>Coupon redeemed successfully!</span>
                                </div>
                                <p className="text-muted">
                                    Your organization now has access to {config.name} benefits.
                                    {claimedDetails?.expires_at &&
                                        ` Valid until ${new Date(claimedDetails.expires_at).toLocaleDateString()}.`}
                                </p>
                                <div className="flex gap-2">
                                    <LemonButton
                                        type="primary"
                                        to={urls.organizationBilling()}
                                        disableClientSideRouting
                                    >
                                        View in billing
                                    </LemonButton>
                                    <LemonButton type="secondary" to={urls.projectHomepage()} disableClientSideRouting>
                                        Return to PostHog
                                    </LemonButton>
                                </div>
                            </div>
                        ) : (
                            <Form
                                logic={couponLogic}
                                formKey="coupon"
                                enableFormOnSubmit
                                className="space-y-3"
                                props={{ campaign }}
                            >
                                <LemonField
                                    name="organization_name"
                                    label="PostHog organization"
                                    info="To claim for a different organization, switch to that organization first"
                                >
                                    <LemonInput disabled />
                                </LemonField>

                                <LemonField name="code" label="Coupon code">
                                    <LemonInput placeholder="XXX-XXXXXXXXXXX" />
                                </LemonField>

                                <LemonButton type="primary" htmlType="submit" className="mt-4">
                                    Redeem coupon
                                </LemonButton>

                                {/* Form-level error */}
                                <LemonField name="_form">
                                    <span />
                                </LemonField>
                            </Form>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
