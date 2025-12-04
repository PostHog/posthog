import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconArrowRight, IconCheck } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { campaignConfigs } from 'scenes/coupons/campaigns'
import { couponLogic } from 'scenes/coupons/couponLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'
import { BillingProductV2Type } from '~/types'

import { onboardingCouponLogic } from './onboardingCouponLogic'

export const scene: SceneExport = {
    component: OnboardingCouponRedemption,
    logic: onboardingCouponLogic,
    paramsToProps: ({ params }) => ({ campaign: params.campaign || '' }),
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

export function OnboardingCouponRedemption(): JSX.Element {
    const { campaign, shouldContinueAfterClaim, alreadyClaimed } = useValues(onboardingCouponLogic)
    const { continueToOnboarding, skipCoupon } = useActions(onboardingCouponLogic)

    const config = campaignConfigs[campaign]
    const logic = couponLogic({ campaign })
    const { claimed, claimedDetails, isAdminOrOwner, isCouponSubmitting, couponsOverviewLoading } = useValues(logic)
    const { billing, billingLoading } = useValues(billingLogic)

    const platformAndSupportProduct = billing?.products?.find(
        (product) => product.type === ProductKey.PLATFORM_AND_SUPPORT
    )

    if (!config) {
        return (
            <div className="flex flex-col items-center justify-center min-h-screen p-4 bg-primary">
                <LemonBanner type="error" className="max-w-lg">
                    <h2 className="mb-2">Invalid campaign</h2>
                    <p>The campaign "{campaign}" was not found.</p>
                    <LemonButton type="primary" onClick={skipCoupon} className="mt-4">
                        Continue to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    if (!isAdminOrOwner) {
        return (
            <div className="flex flex-col items-center justify-center min-h-screen p-4 bg-primary">
                <LemonBanner type="warning" className="max-w-lg">
                    <h2 className="mb-2">Admin or owner permission required</h2>
                    <p>
                        You need to be an organization admin or owner to claim coupons. You can continue setting up
                        PostHog and claim this coupon later.
                    </p>
                    <LemonButton type="primary" onClick={skipCoupon} className="mt-4">
                        Continue setup
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-center justify-center min-h-screen p-4 bg-primary">
            <div className="max-w-4xl w-full">
                {/* Hero section */}
                <div className="flex flex-col items-center mb-8">
                    {config.HeroImage && <config.HeroImage className="h-auto w-full max-w-80 mb-4" />}
                    <div className="text-center">
                        <h1 className="text-3xl sm:text-4xl font-bold mb-2">{config.heroTitle}</h1>
                        <p className="text-lg text-muted">{config.heroSubtitle}</p>
                    </div>
                </div>

                <div className="grid md:grid-cols-2 gap-8 mb-8">
                    {/* Left: Benefits */}
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

                    {/* Right: Claim form */}
                    <div className="space-y-4">
                        {/* Step 1: Add billing details */}
                        <div className="bg-surface-secondary rounded-lg p-6">
                            <h2 className="text-xl mb-4">Step 1: Add billing details</h2>
                            {billingLoading ? (
                                <div className="flex items-center gap-2">
                                    <Spinner className="text-lg" />
                                    <span>Checking billing status...</span>
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

                        {/* Step 2: Redeem coupon */}
                        <div className="bg-surface-secondary rounded-lg p-6">
                            <h2 className="text-xl mb-4">Step 2: Redeem your coupon</h2>

                            {couponsOverviewLoading ? (
                                <div className="flex items-center gap-2">
                                    <Spinner className="text-lg" />
                                    <span>Checking coupon status...</span>
                                </div>
                            ) : claimed ? (
                                <div className="space-y-4">
                                    <div className="flex items-center gap-2 text-success">
                                        <IconCheck className="shrink-0" />
                                        <span>Coupon redeemed successfully!</span>
                                    </div>
                                    <p className="text-muted">
                                        Your organization now has access to {config.name} benefits.
                                        {claimedDetails?.expires_at &&
                                            ` Valid until ${dayjs(claimedDetails.expires_at).format('LL')}.`}
                                    </p>
                                </div>
                            ) : alreadyClaimed ? (
                                <div className="space-y-4">
                                    <div className="flex items-center gap-2 text-success">
                                        <IconCheck className="shrink-0" />
                                        <span>You've already claimed this offer!</span>
                                    </div>
                                    <p className="text-muted">
                                        Your organization has already claimed {config.name} coupon.
                                        {alreadyClaimed.expires_at &&
                                            ` Valid until ${dayjs(alreadyClaimed.expires_at).format('LL')}.`}
                                    </p>
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

                                    <LemonButton
                                        type="primary"
                                        htmlType="submit"
                                        className="mt-4"
                                        loading={isCouponSubmitting}
                                        disabledReason={isCouponSubmitting ? 'Redeeming coupon...' : undefined}
                                    >
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

                {/* Footer actions */}
                <div className="flex justify-center gap-4">
                    {shouldContinueAfterClaim ? (
                        <LemonButton
                            type="primary"
                            status="alt"
                            size="large"
                            sideIcon={<IconArrowRight />}
                            onClick={continueToOnboarding}
                        >
                            Continue to setup
                        </LemonButton>
                    ) : (
                        <LemonButton type="secondary" onClick={skipCoupon}>
                            Skip for now
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}
