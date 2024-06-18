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

    return (
        <div className="flex relative justify-between items-center rounded-lg bg-mark" ref={billingHeroRef}>
            <div className="p-4">
                <h1 className="mb-0">Get the whole hog.</h1>
                <h1 className="text-danger">Only pay for what you use.</h1>
                <div className="mt-2 mb-0 max-w-xl">
                    <p>PostHog comes with all product features on every plan.</p>
                    <p>
                        Add your credit card to remove usage limits and unlock all platform features. Set billing limits
                        as low as $0 to control your spend.
                    </p>
                    <p className="italic">P.S. You still keep the monthly free allotment for every product!</p>
                </div>
                <div className="flex justify-start space-x-2">
                    <LemonButton
                        className="mt-4 inline-block"
                        to={`/api/billing/activate?products=all_products:&redirect_path=${redirectPath}`}
                        type="primary"
                        status="alt"
                        disableClientSideRouting
                        loading={!!billingProductLoading}
                        onClick={() => setBillingProductLoading(product.type)}
                    >
                        Upgrade now
                    </LemonButton>
                    <LemonButton
                        className="mt-4 inline-block"
                        onClick={() => toggleIsPlanComparisonModalOpen()}
                        type="primary"
                    >
                        Compare plans
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
