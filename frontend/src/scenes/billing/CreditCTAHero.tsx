import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BlushingHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import useResizeObserver from 'use-resize-observer'

import { billingLogic } from './billingLogic'
import { PurchaseCreditsModal } from './PurchaseCreditsModal'

export const CreditCTAHero = (): JSX.Element | null => {
    const { width, ref: heroRef } = useResizeObserver()

    const { creditOverview, isPurchaseCreditsModalOpen } = useValues(billingLogic)
    const { showPurchaseCreditsModal } = useActions(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!creditOverview.eligible || creditOverview.status === 'paid') {
        return null
    }
    if (!featureFlags[FEATURE_FLAGS.PURCHASE_CREDITS]) {
        return null
    }

    return (
        <div className="flex relative justify-between items-center rounded-lg bg-mark mb-6" ref={heroRef}>
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
                            Buy credits in advance, at a discount of up to 30%. It helps you make costs more
                            predictable!
                        </p>
                        <LemonButton type="primary" onClick={() => showPurchaseCreditsModal(true)} className="mt-4">
                            Buy credits
                        </LemonButton>
                    </>
                )}
            </div>
            {width && width > 500 && (
                <div className="shrink-0 relative w-50 pt-4 overflow-hidden">
                    <BlushingHog className="w-50 h-50 -my-5" />
                </div>
            )}
            {isPurchaseCreditsModalOpen && <PurchaseCreditsModal />}
        </div>
    )
}
