import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BlushingHog } from 'lib/components/hedgehogs'
import useResizeObserver from 'use-resize-observer'

import { BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { PlanComparisonModal } from './PlanComparison'

export const BillingCTAHero = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { width, ref: billingHeroRef } = useResizeObserver()

    const { redirectPath } = useValues(billingLogic)
    const { isPlanComparisonModalOpen, billingProductLoading } = useValues(billingProductLogic({ product }))
    const { toggleIsPlanComparisonModalOpen, setBillingProductLoading } = useActions(billingProductLogic({ product }))

    // TODO(@zach): add multiple variations of this copy
    return (
        <div className="flex relative justify-between items-center rounded-lg bg-mark" ref={billingHeroRef}>
            <div className="p-4">
                <h1>Subscribe to unlock all the features.</h1>
                <h1 className="text-danger">Only pay for what you use.</h1>
                <p className="mt-2 mb-0">
                    You're currently on the free plan. It's free but limited in features. Subscribe and upgrade to our
                    paid plan where you pay per use (after the generous free tier).
                </p>
                <div className="flex justify-start space-x-2">
                    <LemonButton
                        className="mt-4 inline-block"
                        onClick={() => toggleIsPlanComparisonModalOpen()}
                        type="secondary"
                    >
                        Compare plans
                    </LemonButton>
                    <LemonButton
                        className="mt-4 inline-block"
                        to={`/api/billing/activation?products=all_products:&redirect_path=${redirectPath}`}
                        type="primary"
                        disableClientSideRouting
                        loading={!!billingProductLoading}
                        onClick={() => setBillingProductLoading(product.type)}
                    >
                        Subscribe now!
                    </LemonButton>
                </div>
            </div>
            {width && width > 500 && (
                <div className="shrink-0 relative w-50 pt-4 overflow-hidden">
                    <BlushingHog className="w-50 h-50 -my-5" />
                </div>
            )}
            <PlanComparisonModal
                product={product}
                title="Compare our plans"
                includeAddons={false}
                modalOpen={isPlanComparisonModalOpen}
                onClose={() => toggleIsPlanComparisonModalOpen()}
            />
        </div>
    )
}
