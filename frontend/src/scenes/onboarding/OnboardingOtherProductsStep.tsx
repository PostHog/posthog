import { LemonButton, LemonCard } from '@posthog/lemon-ui'
import { OnboardingStep } from './OnboardingStep'
import { onboardingLogic } from './onboardingLogic'
import { useActions, useValues } from 'kea'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'

export const OnboardingOtherProductsStep = (): JSX.Element => {
    const { product } = useValues(onboardingLogic)
    const { completeOnboarding } = useActions(onboardingLogic)
    const { billing } = useValues(billingLogic)
    const suggestedProducts = billing?.products?.filter(
        (p) => p.type !== product?.type && !p.contact_support && !p.inclusion_only
    )

    return (
        <OnboardingStep
            title={`${product?.name} pairs with...`}
            subtitle="The magic in PostHog is having everyting all in one place. Get started with our other products to unlock your product and data superpowers."
            showSkip
            continueOverride={<></>}
        >
            <div className="flex flex-col gap-y-6 my-6">
                {suggestedProducts?.map((suggestedProduct) => (
                    <LemonCard
                        className="flex items-center justify-between"
                        hoverEffect={false}
                        key={suggestedProduct.type}
                    >
                        <div className="flex items-center">
                            <div className="mr-4">
                                <img
                                    src={suggestedProduct.image_url || ''}
                                    alt={suggestedProduct.name}
                                    className="w-8 h-8"
                                />
                            </div>
                            <div>
                                <h3 className="font-bold mb-0">{suggestedProduct.name}</h3>
                                <p className="m-0">{suggestedProduct.description}</p>
                            </div>
                        </div>
                        <div className="justify-self-end min-w-30 flex justify-end">
                            <LemonButton
                                type="primary"
                                onClick={() => completeOnboarding(urls.onboarding(suggestedProduct.type))}
                            >
                                Get started
                            </LemonButton>
                        </div>
                    </LemonCard>
                ))}
            </div>
        </OnboardingStep>
    )
}
