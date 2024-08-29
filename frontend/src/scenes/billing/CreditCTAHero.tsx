import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BlushingHog } from 'lib/components/hedgehogs'
import useResizeObserver from 'use-resize-observer'

import { billingLogic } from './billingLogic'
import { PurchaseCreditModal } from './PurchaseCreditModal'

export const CreditCTAHero = (): JSX.Element | null => {
    const { width, ref: heroRef } = useResizeObserver()

    const { selfServeCreditEligibility, isPurchaseCreditModalOpen } = useValues(billingLogic)
    const { showPurchaseCreditModal } = useActions(billingLogic)

    // if (!selfServeCreditEligibility.eligible || selfServeCreditEligibility.status === "paid") {
    if (!selfServeCreditEligibility.eligible) {
        return null
    }

    return (
        <div className="flex relative justify-between items-center rounded-lg bg-mark mb-6" ref={heroRef}>
            <div className="p-4">
                {selfServeCreditEligibility.eligible && selfServeCreditEligibility.status === 'pending' && (
                    <>
                        <h1 className="mb-0">Your credits are processing</h1>
                        <p className="mt-2 mb-0 max-w-xl">
                            You've initiated the process to purchase credits.{' '}
                            {selfServeCreditEligibility.collection_method === 'send_invoice'
                                ? "You'll receive an email with a link to pay the invoice. Please make sure to pay that as soon as possible so we can apply the credits to your account."
                                : "We'll will charge your card on file and we will notify if there are any issues."}{' '}
                            The credits should be applied ot your account within 24 hours of completing your payment.{' '}
                        </p>
                        {selfServeCreditEligibility.invoice_url && (
                            <LemonButton
                                type="primary"
                                onClick={() => window.open(selfServeCreditEligibility.invoice_url, '_blank')}
                                className="mt-4"
                            >
                                View invoice
                            </LemonButton>
                        )}
                    </>
                )}
                {/* {selfServeCreditEligibility.eligible && selfServeCreditEligibility.status === "none" && ( */}
                {selfServeCreditEligibility.eligible &&
                    (selfServeCreditEligibility.status === 'none' || selfServeCreditEligibility.status === 'paid') && (
                        <>
                            <h1 className="mb-0">You're eligible to purchase credits</h1>
                            <p className="mt-2 mb-0 max-w-xl">
                                You're eligible to purchase credits. Buy credits upfront to get a discount and make your
                                PostHog payments more predictable.
                            </p>
                            <LemonButton type="primary" onClick={() => showPurchaseCreditModal(true)} className="mt-4">
                                Purchase credits
                            </LemonButton>
                        </>
                    )}
            </div>
            {width && width > 500 && (
                <div className="shrink-0 relative w-50 pt-4 overflow-hidden">
                    <BlushingHog className="w-50 h-50 -my-5" />
                </div>
            )}
            {isPurchaseCreditModalOpen && <PurchaseCreditModal />}
        </div>
    )
}
