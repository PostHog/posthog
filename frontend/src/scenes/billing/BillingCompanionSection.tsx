import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { BillingProductV2Type } from '~/types'

import { createGaugeItems, isBillingLimitShown } from './billing-utils'
import { BillingGauge } from './BillingGauge'
import { billingLogic } from './billingLogic'
import { billingProductDisplayName, billingProductRowDisplayName } from './billingProductDisplayName'
import { billingProductLogic } from './billingProductLogic'
import { BillingProductPricingTable } from './BillingProductPricingTable'

// Companions bill under the parent card but outside its billing limit, so the card's own amounts leave them out.
export const BillingCompanionSection = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const { billing, isUnlicensedDebug } = useValues(billingLogic)
    const { noLimitCompanionAmounts, totalsIncludingCompanions, variantExpandedStates } = useValues(
        billingProductLogic({ product })
    )
    const { toggleVariantExpanded } = useActions(billingProductLogic({ product }))

    if (isUnlicensedDebug || noLimitCompanionAmounts.length === 0) {
        return null
    }

    const periodLabel = `${billing?.billing_period?.interval || 'month'}-to-date`

    return (
        <div className="border-t border-primary px-8 py-4" data-attr={`billing-companions-${product.type}`}>
            <h4 className="mb-0">Not covered by your billing limit</h4>
            {isBillingLimitShown(product, billing) && (
                <p className="text-sm text-secondary mb-0">
                    Your {billingProductDisplayName(product)} billing limit does not cap these charges.
                </p>
            )}
            <div className="space-y-4 mt-4">
                {noLimitCompanionAmounts.map(({ companion, currentAmount, projectedAmount }) => {
                    const isExpanded = !!variantExpandedStates?.[companion.type]
                    const displayName = billingProductRowDisplayName(companion)
                    return (
                        <div key={companion.type} data-attr={`billing-companion-${companion.type}`}>
                            <div className="grid grid-cols-[auto_1fr_130px_100px] gap-4 items-center">
                                <LemonButton
                                    icon={isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                                    size="small"
                                    aria-label={`${isExpanded ? 'Hide' : 'Show'} ${displayName} details`}
                                    onClick={() => toggleVariantExpanded(companion.type)}
                                />
                                <h4 className="mb-0 font-bold">{displayName}</h4>
                                <div className="flex flex-col items-end">
                                    <span className="font-bold text-lg leading-5">
                                        {humanFriendlyCurrency(currentAmount)}
                                    </span>
                                    <span className="text-xs text-secondary">{capitalizeFirstLetter(periodLabel)}</span>
                                </div>
                                <div className="flex flex-col items-end">
                                    <span className="text-secondary text-lg leading-5">
                                        {humanFriendlyCurrency(projectedAmount)}
                                    </span>
                                    <span className="text-xs text-secondary">Projected</span>
                                </div>
                            </div>
                            {isExpanded && (
                                <div className="mt-4">
                                    <div className="ml-16">
                                        <BillingGauge items={createGaugeItems(companion)} product={companion} />
                                    </div>
                                    <BillingProductPricingTable product={companion} />
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
            {product.subscribed && (
                <p className="text-sm mt-4 mb-0" data-attr={`billing-companions-total-${product.type}`}>
                    <span>Total including this section:&nbsp;</span>
                    <span translate="no">{humanFriendlyCurrency(totalsIncludingCompanions.currentTotal)}</span>
                    <span>{`\u00a0${periodLabel},\u00a0`}</span>
                    <span translate="no">{humanFriendlyCurrency(totalsIncludingCompanions.projectedTotal)}</span>
                    <span>&nbsp;projected</span>
                </p>
            )}
        </div>
    )
}
