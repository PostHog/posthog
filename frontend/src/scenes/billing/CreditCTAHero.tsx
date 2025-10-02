import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'

import { BurningMoneyHog } from 'lib/components/hedgehogs'

import { PurchaseCreditsModal } from './PurchaseCreditsModal'
import { billingLogic } from './billingLogic'

export const DEFAULT_ESTIMATED_MONTHLY_CREDIT_AMOUNT_USD = 500

export const CreditCTAHero = (): JSX.Element | null => {
    const {
        creditOverview,
        isPurchaseCreditsModalOpen,
        isCreditCTAHeroDismissed,
        computedDiscount,
        showCreditCTAHero,
    } = useValues(billingLogic)
    const { showPurchaseCreditsModal, toggleCreditCTAHeroDismissed } = useActions(billingLogic)
    const { estimatedMonthlyCreditAmountUsd } = useValues(billingLogic)

    if (!showCreditCTAHero) {
        return null
    }

    if (isCreditCTAHeroDismissed) {
        return (
            <div className="absolute top-0 right-0 z-10">
                <div
                    className="cursor-pointer border border-accent rounded-lg pr-3 pl-2 py-1 hover:bg-accent-highlight-secondary transition-colors group"
                    onClick={() => toggleCreditCTAHeroDismissed(false)}
                >
                    <span className="flex items-center gap-1.5">
                        <BurningMoneyHog
                            className="w-8 h-8 group-hover:animate-bounce"
                            style={{ animationDuration: '0.75s' }}
                        />
                        <span>Get {computedDiscount! * 100}% off</span>
                    </span>
                </div>
            </div>
        )
    }

    return (
        <div className="relative rounded-lg bg-surface-primary border mb-2">
            <div className="absolute top-2 right-2 z-10">
                <LemonButton
                    icon={<IconX className="w-4 h-4" />}
                    size="small"
                    onClick={() => toggleCreditCTAHeroDismissed(true)}
                    aria-label="Close"
                />
            </div>
            <div className="@container p-4 relative">
                <div className="flex gap-6 mb-4">
                    <div className="flex-1">
                        {creditOverview.status === 'pending' && (
                            <>
                                <h1 className="mb-0">We're applying your credits</h1>
                                <p className="mt-2 mb-0">
                                    Your credits will be ready within 24 hours of payment.{' '}
                                    {creditOverview.collection_method === 'send_invoice' ? (
                                        <>
                                            You'll receive an email with a link to pay the invoice. Please make sure to
                                            pay that as soon as possible so we can apply the credits to your account.
                                        </>
                                    ) : (
                                        <>
                                            We'll will charge your card on file and we'll email you if there are any
                                            issues!"
                                        </>
                                    )}
                                </p>
                            </>
                        )}
                        {creditOverview.status === 'none' && (
                            <>
                                <h2 className="mb-0">
                                    Stop burning money.{' '}
                                    <span className="text-success-light">
                                        Prepay and save{' '}
                                        {computedDiscount !== null ? (
                                            computedDiscount * 100
                                        ) : (
                                            <LemonSkeleton className="inline-block h-5 w-18 rounded align-text-bottom" />
                                        )}
                                        %
                                    </span>{' '}
                                    over the next 12 months.
                                </h2>
                                <p className="mt-2 mb-0">
                                    Based on your usage, your monthly bill is forecasted to be an average of{' '}
                                    {estimatedMonthlyCreditAmountUsd === null ? (
                                        <LemonSkeleton className="inline-block h-4 w-18 rounded align-text-bottom" />
                                    ) : (
                                        <strong>{estimatedMonthlyCreditAmountUsd.toFixed(0)}/month</strong>
                                    )}{' '}
                                    over the next year.
                                </p>
                                <p className="mt-2 mb-0">
                                    This qualifies you for a{' '}
                                    {estimatedMonthlyCreditAmountUsd === null ? (
                                        <LemonSkeleton className="inline-block h-4 w-18 rounded align-text-bottom" />
                                    ) : (
                                        <strong>{computedDiscount! * 100}% discount</strong>
                                    )}{' '}
                                    by pre-purchasing usage credits. Which gives you a net savings of{' '}
                                    {estimatedMonthlyCreditAmountUsd === null ? (
                                        <LemonSkeleton className="inline-block h-4 w-18 rounded align-text-bottom" />
                                    ) : (
                                        <strong>
                                            $
                                            {Math.round(
                                                estimatedMonthlyCreditAmountUsd * computedDiscount! * 12
                                            ).toLocaleString('en-US', {
                                                minimumFractionDigits: 0,
                                                maximumFractionDigits: 0,
                                            })}
                                        </strong>
                                    )}{' '}
                                    over the next year.
                                </p>
                                <p className="mt-2 mb-0">Ready to save money on your PostHog usage?</p>
                            </>
                        )}
                    </div>
                    <div className="flex flex-col justify-center items-end w-30">
                        <BurningMoneyHog className="w-full h-auto" />
                        {creditOverview.status === 'pending' && creditOverview.invoice_url && (
                            <LemonButton
                                type="primary"
                                onClick={() =>
                                    creditOverview.invoice_url && window.open(creditOverview.invoice_url, '_blank')
                                }
                                className="w-30 mt-4"
                            >
                                View invoice
                            </LemonButton>
                        )}
                        {creditOverview.status === 'none' && (
                            <LemonButton
                                type="primary"
                                status="alt"
                                onClick={() => showPurchaseCreditsModal(true)}
                                className="w-30 mt-4"
                            >
                                Learn more
                            </LemonButton>
                        )}
                    </div>
                </div>

                {creditOverview.status === 'none' && (
                    <>
                        <LemonDivider className="my-3" />
                        <div className="flex items-center justify-between gap-6">
                            <p className="mb-0 flex-1">
                                <strong>Also available:</strong> Our Enterprise tier offers dedicated support in a
                                private Slack channel, personalized training, and most importantly, free merch.
                            </p>
                            <LemonButton
                                type="primary"
                                to="mailto:sales@posthog.com?subject=Let's talk enterprise!"
                                className="w-30"
                            >
                                Talk to sales
                            </LemonButton>
                        </div>
                    </>
                )}
            </div>
            {isPurchaseCreditsModalOpen && <PurchaseCreditsModal />}
        </div>
    )
}
