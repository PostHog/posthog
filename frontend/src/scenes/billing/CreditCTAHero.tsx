import { IconX } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BurningMoneyHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import useResizeObserver from 'use-resize-observer'

import { billingLogic } from './billingLogic'
import { PurchaseCreditsModal } from './PurchaseCreditsModal'

export const CreditCTAHero = (): JSX.Element | null => {
    const { width, ref: heroRef } = useResizeObserver()

    const { creditOverview, isPurchaseCreditsModalOpen, isCreditCTAHeroDismissed, computedDiscount } =
        useValues(billingLogic)
    const { showPurchaseCreditsModal, toggleCreditCTAHeroDismissed } = useActions(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!creditOverview.eligible || creditOverview.status === 'paid') {
        return null
    }
    if (!featureFlags[FEATURE_FLAGS.PURCHASE_CREDITS]) {
        return null
    }

    if (isCreditCTAHeroDismissed) {
        return (
            <div className="absolute top-0 right-0 z-10">
                <div
                    className="cursor-pointer bg-mark rounded-lg pr-3 pl-2 py-1 hover:bg-mark-light transition-colors group"
                    onClick={() => toggleCreditCTAHeroDismissed(false)}
                >
                    <span className="flex items-center gap-1.5">
                        <BurningMoneyHog
                            className="w-8 h-8 group-hover:animate-bounce"
                            style={{ animationDuration: '0.75s' }}
                        />
                        <span>Get {computedDiscount * 100}% off</span>
                    </span>
                </div>
            </div>
        )
    }

    return (
        <div
            className="flex relative justify-between items-start rounded-lg bg-bg-light border mb-2 gap-2"
            ref={heroRef}
        >
            <div className="absolute top-2 right-2 z-10">
                <LemonButton
                    icon={<IconX className="w-4 h-4" />}
                    size="small"
                    onClick={() => toggleCreditCTAHeroDismissed(true)}
                    aria-label="Close"
                />
            </div>
            {width && width > 500 && (
                <div className="shrink-0 relative pt-4 overflow-hidden">
                    <BurningMoneyHog className="w-40 h-40" />
                </div>
            )}
            <div className="p-4 flex-1">
                {creditOverview.eligible && creditOverview.status === 'pending' && (
                    <>
                        <h1 className="mb-0">We're applying your credits</h1>
                        <p className="mt-2 mb-0 max-w-xl">
                            Your credits will be ready within 24 hours of payment.{' '}
                            {creditOverview.collection_method === 'send_invoice'
                                ? "You'll receive an email with a link to pay the invoice. Please make sure to pay that as soon as possible so we can apply the credits to your account."
                                : "We'll will charge your card on file and we'll email you if there are any issues!"}
                        </p>
                        {creditOverview.invoice_url && (
                            <LemonButton
                                type="primary"
                                onClick={() =>
                                    creditOverview.invoice_url && window.open(creditOverview.invoice_url, '_blank')
                                }
                                className="mt-4"
                            >
                                View invoice
                            </LemonButton>
                        )}
                    </>
                )}
                {creditOverview.eligible && creditOverview.status === 'none' && (
                    <>
                        <h2 className="mb-0">
                            Stop burning money.{' '}
                            <span className="text-success-light">Prepay and save {computedDiscount * 100}%</span> over
                            the next 12 months.
                        </h2>
                        <p className="mt-2 mb-0 max-w-xl">
                            Based on your usage, your monthly bill is forecasted to be an average of{' '}
                            <strong>${creditOverview.estimated_monthly_credit_amount_usd.toFixed(0)}/month</strong> over
                            the next year.
                        </p>
                        <p className="mt-2 mb-0 max-w-xl">
                            This qualifies you for a <strong>{computedDiscount * 100}% discount</strong> by
                            pre-purchasing usage credits. Which gives you a net savings of{' '}
                            <strong>
                                $
                                {Math.round(
                                    creditOverview.estimated_monthly_credit_amount_usd * computedDiscount * 12
                                ).toLocaleString('en-US', {
                                    minimumFractionDigits: 0,
                                    maximumFractionDigits: 0,
                                })}
                            </strong>{' '}
                            over the next year.
                        </p>
                        <LemonButton
                            type="primary"
                            status="alt"
                            onClick={() => showPurchaseCreditsModal(true)}
                            className="mt-4"
                        >
                            Learn more
                        </LemonButton>
                        {creditOverview.estimated_monthly_credit_amount_usd > 1 && (
                            <>
                                <LemonDivider className="my-4" />
                                <div className="mt-2 flex justify-between items-center gap-2 w-full">
                                    <p className="mb-2 flex-1">
                                        <strong>Also available:</strong> Our Enterprise tier offers dedicated support in
                                        a private Slack channel, personalized training, and most importantly, free
                                        merch.
                                    </p>
                                    <LemonButton
                                        type="primary"
                                        to="mailto:sales@posthog.com?subject=Let's talk enterprise!"
                                    >
                                        Talk to sales
                                    </LemonButton>
                                </div>
                            </>
                        )}
                    </>
                )}
            </div>
            {isPurchaseCreditsModalOpen && <PurchaseCreditsModal />}
        </div>
    )
}
