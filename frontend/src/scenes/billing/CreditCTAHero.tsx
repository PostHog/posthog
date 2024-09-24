import { IconCheckCircle, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BlushingHog, SurprisedHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import useResizeObserver from 'use-resize-observer'

import { billingLogic } from './billingLogic'
import { PurchaseCreditsModal } from './PurchaseCreditsModal'

export const CreditCTAHero = (): JSX.Element | null => {
    const { width, ref: heroRef } = useResizeObserver()

    const { creditOverview, isPurchaseCreditsModalOpen, isCreditCTAHeroDismissed } = useValues(billingLogic)
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
                    className="cursor-pointer bg-mark rounded-lg pr-2 pl-3 py-1 hover:bg-mark-light transition-colors group"
                    onClick={() => toggleCreditCTAHeroDismissed(false)}
                >
                    <span className="flex items-center gap-1.5">
                        <span>Get up to 30% off</span>
                        <BlushingHog
                            className="w-8 h-8 group-hover:animate-bounce"
                            style={{ animationDuration: '0.75s' }}
                        />
                    </span>
                </div>
            </div>
        )
    }

    return (
        <div className="flex relative justify-between items-center rounded-lg bg-mark mb-6" ref={heroRef}>
            <div className="absolute top-2 right-2">
                <LemonButton
                    icon={<IconX className="w-4 h-4" />}
                    size="small"
                    onClick={() => toggleCreditCTAHeroDismissed(true)}
                    aria-label="Close"
                />
            </div>
            <div className="p-4">
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
                        <h1 className="mb-0">Get a discount of up to 30%</h1>
                        <p className="mt-2 mb-0 max-w-xl">
                            You're eligible to buy credits in advance, at a discount of up to 30%. It helps you make
                            costs more predictable!
                        </p>
                        <LemonButton type="primary" onClick={() => showPurchaseCreditsModal(true)} className="mt-4">
                            Buy credits
                        </LemonButton>
                        {creditOverview.estimated_monthly_credit_amount_usd > 1667 && (
                            <>
                                <LemonDivider className="my-4" />
                                <div className="mt-2 mb-0 max-w-xl">
                                    <p className="mb-2">
                                        Looking for even more? Our enterprise plan is waiting for you ...
                                    </p>
                                    <ul className="pl-4">
                                        <li className="flex gap-2 items-center">
                                            <IconCheckCircle className="text-success shrink-0" />
                                            <span>
                                                Get <strong>customized training</strong> for you and your team
                                            </span>
                                        </li>
                                        <li className="flex gap-2 items-center">
                                            <IconCheckCircle className="text-success shrink-0" />
                                            <span>
                                                Get dedicated support via <strong>private Slack channel</strong>
                                            </span>
                                        </li>
                                        <li className="flex gap-2 items-center">
                                            <IconCheckCircle className="text-success shrink-0" />
                                            <span>
                                                We'll even send you <strong>awesome free merch</strong>
                                            </span>
                                        </li>
                                    </ul>
                                    <p className="mt-2 mb-0">
                                        <Link to="mailto:sales@posthog.com?subject=Let's talk enterprise!">
                                            Talk to sales
                                        </Link>{' '}
                                        to learn more.
                                    </p>
                                </div>
                            </>
                        )}
                    </>
                )}
            </div>
            {width && width > 500 && (
                <div className="shrink-0 relative w-50 pt-4 overflow-hidden">
                    <SurprisedHog className="w-50 h-50 -my-5 scale-x-[-1]" />
                </div>
            )}
            {isPurchaseCreditsModalOpen && <PurchaseCreditsModal />}
        </div>
    )
}
