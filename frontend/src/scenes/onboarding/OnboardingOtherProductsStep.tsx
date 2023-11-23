import { useActions, useValues } from 'kea'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { ProductCard } from 'scenes/products/Products'

import { onboardingLogic, OnboardingStepKey } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

export const OnboardingOtherProductsStep = ({
    stepKey = OnboardingStepKey.OTHER_PRODUCTS,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const { product, suggestedProducts } = useValues(onboardingLogic)
    const { completeOnboarding } = useActions(onboardingLogic)
    const { width } = useWindowSize()
    const horizontalCard = width && width >= 640

    return (
        <OnboardingStep
            title={`${product?.name} pairs with...`}
            subtitle="The magic in PostHog is having everything all in one place. Get started with our other products to unlock your product and data superpowers."
            showSkip
            continueOverride={<></>}
            stepKey={stepKey}
        >
            <div className="flex flex-col gap-y-6 my-6 items-center">
                {suggestedProducts?.map((suggestedProduct) => (
                    <ProductCard
                        product={suggestedProduct}
                        key={suggestedProduct.type}
                        getStartedActionOverride={() => completeOnboarding(suggestedProduct.type)}
                        orientation={horizontalCard ? 'horizontal' : 'vertical'}
                        className="w-full"
                    />
                ))}
            </div>
        </OnboardingStep>
    )
}
