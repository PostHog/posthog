import { pluralize } from 'lib/utils/strings'
import { freePrs, pricePerPrUsd } from 'scenes/billing/inboxPricing'
import { StatFigure } from 'scenes/onboarding/self-driving/components/StatFigure'
import { formatUsd } from 'scenes/onboarding/self-driving/utils'

import { type BillingProductV2Type } from '~/types'

/**
 * The headline: what self-driving costs, before the plans that differ only in what happens after
 * the free PRs run out.
 *
 * The numbers are optional on purpose. Billing may not carry the inbox product (an instance without
 * it in its plans config, or a request that came back thin), and the pricing model is still the
 * point of this screen, so the copy stands on its own and only the figures drop out.
 */
export function SelfDrivingPricing({ product }: { product: BillingProductV2Type | null }): JSX.Element {
    const included = freePrs(product)
    const perPr = pricePerPrUsd(product)

    return (
        <div className="w-full flex flex-col gap-3 p-4 rounded-lg border border-accent bg-accent-highlight">
            <p className="m-0 text-sm font-semibold">You pay for shipped work, nothing else</p>
            {(included > 0 || perPr !== null) && (
                <div className="flex flex-wrap items-start gap-x-10 gap-y-3">
                    {included > 0 && (
                        <StatFigure
                            value={included}
                            label={`${pluralize(included, 'pull request', undefined, false)} a month, free`}
                        />
                    )}
                    {perPr !== null && <StatFigure value={formatUsd(perPr)} label="per pull request after that" />}
                </div>
            )}
            <p className="m-0 text-xs text-muted">
                Scouts, signals, and reports never cost anything. You're charged only when an agent ships a pull request
                you can review.
            </p>
        </div>
    )
}
