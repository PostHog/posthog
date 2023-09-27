import { useActions, useValues } from 'kea'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { onboardingLogic } from './onboardingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { convertLargeNumberToWords } from 'scenes/billing/billing-utils'
import { BillingProductV2Type } from '~/types'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { ProductPricingModal } from 'scenes/billing/ProductPricingModal'
import { IconArrowLeft, IconCheckCircleOutline, IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

export const OnboardingProductIntro = ({
    product,
    onStart,
}: {
    product: BillingProductV2Type
    onStart?: () => void
}): JSX.Element => {
    const { currentAndUpgradePlans, isPricingModalOpen } = useValues(billingProductLogic({ product }))
    const { toggleIsPricingModalOpen } = useActions(billingProductLogic({ product }))
    const { setCurrentOnboardingStepNumber } = useActions(onboardingLogic)
    const { currentOnboardingStepNumber } = useValues(onboardingLogic)

    const pricingBenefits = [
        'Only pay for what you use',
        'Control spend with billing limits as low as $0/mo',
        'Generous free volume every month, forever',
    ]

    const productWebsiteKey = product.type.replace('_', '-')
    const communityUrl = 'https://posthog.com/questions/topic/' + productWebsiteKey
    const tutorialsUrl = 'https://posthog.com/tutorials/categories/' + productWebsiteKey
    const productPageUrl = 'https://posthog.com/' + productWebsiteKey
    const productImageUrl = `https://posthog.com/images/product/${productWebsiteKey}-product.png`

    const upgradePlan = currentAndUpgradePlans?.upgradePlan
    const plan = upgradePlan ? upgradePlan : currentAndUpgradePlans?.currentPlan

    return (
        <div className="w-full">
            <div className="flex flex-col w-full p-6 bg-mid items-center justify-center">
                <div className="max-w-lg flex flex-wrap my-8 items-center">
                    <div className="w-1/2 pr-6 min-w-80">
                        <div className="flex mb-6">
                            <LemonButton
                                to={urls.products()}
                                icon={<IconArrowLeft />}
                                type="tertiary"
                                status="muted"
                                noPadding
                                size="small"
                            >
                                <span className="pr-1">All products</span>
                            </LemonButton>
                        </div>
                        <h1 className="text-5xl font-bold">{product.name}</h1>
                        <h2 className="font-bold mb-6">{product.description}</h2>
                        <div className="flex gap-x-2">
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    onStart && onStart()
                                    setCurrentOnboardingStepNumber(currentOnboardingStepNumber + 1)
                                }}
                            >
                                Get started
                            </LemonButton>
                            {product.docs_url && (
                                <LemonButton type="secondary" to={productPageUrl}>
                                    Learn more
                                </LemonButton>
                            )}
                        </div>
                    </div>
                    <div className="shrink w-1/2 min-w-80">
                        <img src={productImageUrl} className="w-full" />
                    </div>
                </div>
            </div>
            <div className="my-12 flex justify-between mx-auto max-w-lg gap-x-8">
                <div className="flex flex-col">
                    <h2 className="text-3xl">Features</h2>
                    <div className="flex flex-wrap gap-y-4 my-6 max-w-lg">
                        {plan?.features?.map((feature, i) => (
                            <li className="flex mb-2" key={`product-features-${i}`}>
                                <div>
                                    <IconCheckCircleOutline className="text-success mr-2 mt-1 w-6" />
                                </div>
                                <div>
                                    <h4 className="font-bold mb-0">{feature.name}</h4>
                                    <p className="m-0">{feature.description}</p>
                                </div>
                            </li>
                        ))}
                    </div>
                </div>
                <div>
                    <LemonCard hoverEffect={false}>
                        <h2 className="text-3xl">Pricing</h2>
                        {plan?.tiers?.[0].unit_amount_usd && parseInt(plan?.tiers?.[0].unit_amount_usd) === 0 && (
                            <p className="ml-0 mb-0 mt-4">
                                <span className="font-bold">
                                    First {convertLargeNumberToWords(plan?.tiers?.[0].up_to, null)} {product.unit}s free
                                </span>
                                , then <span className="font-bold">${plan?.tiers?.[1].unit_amount_usd}</span>
                                <span className="text-muted">/{product.unit}</span>.{' '}
                                <Link
                                    onClick={() => {
                                        toggleIsPricingModalOpen()
                                    }}
                                >
                                    <span className="font-bold text-brand-red">Volume discounts</span>
                                </Link>{' '}
                                after {convertLargeNumberToWords(plan?.tiers?.[1].up_to, null)}/mo.
                            </p>
                        )}
                        <ul>
                            {pricingBenefits.map((benefit, i) => (
                                <li className="flex mb-2 ml-6" key={`pricing-benefits-${i}`}>
                                    <IconCheckCircleOutline className="text-success mr-2 mt-1" />
                                    {benefit}
                                </li>
                            ))}
                        </ul>
                    </LemonCard>
                    <LemonCard className="mt-8" hoverEffect={false}>
                        <h2 className="text-3xl">Resources</h2>
                        {product.docs_url && (
                            <p>
                                <Link to={product.docs_url}>
                                    Documentation <IconOpenInNew />
                                </Link>
                            </p>
                        )}
                        <p>
                            <Link to={communityUrl}>
                                Community forum <IconOpenInNew />
                            </Link>
                        </p>
                        <p>
                            <Link to={tutorialsUrl}>
                                Tutorials <IconOpenInNew />
                            </Link>
                        </p>
                    </LemonCard>
                </div>
            </div>
            <ProductPricingModal
                modalOpen={isPricingModalOpen}
                onClose={toggleIsPricingModalOpen}
                product={product}
                planKey={plan?.plan_key}
            />
        </div>
    )
}
