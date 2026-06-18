import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { SupermanHog } from 'lib/components/hedgehogs'
import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { PlatformAddonComparison } from 'scenes/billing/PlatformAddonComparison'

import { ProductKey } from '~/queries/schema/schema-general'
import { type BillingProductV2Type, OnboardingStepKey } from '~/types'

import { onboardingLogic, OnboardingStepComponentType } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import PlanCards from './PlanCards'

type OnboardingUpgradeStepProps = {
    product: BillingProductV2Type
}

export const OnboardingUpgradeStep: OnboardingStepComponentType<OnboardingUpgradeStepProps> = ({ product }) => {
    const { billing, billingLoading } = useValues(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { goToNextStep } = useActions(onboardingLogic)
    const { reportOnboardingStepSkipped } = useActions(eventUsageLogic)

    if (billingLoading) {
        return (
            <div className="flex items-center justify-center my-20">
                <Spinner className="text-2xl text-muted w-10 h-10" />
            </div>
        )
    }

    const platformProduct = billing?.products?.find((p) => p.type === ProductKey.PLATFORM_AND_SUPPORT)
    const showPlatformPackages =
        !!product.subscribed && featureFlags[FEATURE_FLAGS.ONBOARDING_PLATFORM_PACKAGES] === 'test' && !!platformProduct
    // The package the org is currently trialing, if any (billing.trial.target is the addon type; a
    // 'paid'-plan trial won't match a platform addon, so it stays undefined here).
    const trialAddon = platformProduct?.addons?.find((addon) => addon.type === billing?.trial?.target)

    const skipPlatformPackages = (): void => {
        reportOnboardingStepSkipped(OnboardingStepKey.PLANS)
        goToNextStep()
    }

    return (
        <OnboardingStep
            title="Select a plan"
            stepKey={OnboardingStepKey.PLANS}
            // The packages screen carries its own heading and an above-the-fold skip, so the
            // "Select a plan" title (misleading once subscribed) and the bottom Next are dropped there.
            hideTitle={showPlatformPackages}
            showContinue={!!product.subscribed && !showPlatformPackages}
            actions={
                showPlatformPackages ? (
                    <LemonButton type="secondary" onClick={skipPlatformPackages} data-attr="onboarding-skip-button">
                        {trialAddon ? 'Continue' : 'Skip for now'}
                    </LemonButton>
                ) : undefined
            }
        >
            {!product.subscribed && <PlanCards product={product} />}
            {product.subscribed && !showPlatformPackages && <SubscribedCelebration product={product} />}
            {showPlatformPackages && platformProduct && (
                <PlatformPackagesUpsell platformProduct={platformProduct} trialPackageName={trialAddon?.name} />
            )}
        </OnboardingStep>
    )
}
OnboardingUpgradeStep.stepKey = OnboardingStepKey.PLANS

const SubscribedCelebration = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { trigger, HogfettiComponent } = useHogfetti({ count: 100, duration: 3000 })

    useEffect(() => {
        const run = async (): Promise<void> => {
            trigger()
            await new Promise((resolve) => setTimeout(resolve, 1000))
            trigger()
            await new Promise((resolve) => setTimeout(resolve, 1000))
            trigger()
        }

        void run()
    }, [trigger])

    return (
        <div className="relative flex flex-col items-center text-center">
            <HogfettiComponent />

            {/* Superman Hog floating animation */}
            <div className="w-40 h-40 animate-float">
                <SupermanHog className="w-full h-full object-contain" />
            </div>

            <h3 className="text-2xl font-bold mt-6">Go forth and build amazing products!</h3>
            <p className="text-gray-700 dark:text-gray-400">
                You've unlocked all features for <strong>{product.name}</strong>.
            </p>
        </div>
    )
}

const PlatformPackagesUpsell = ({
    platformProduct,
    trialPackageName,
}: {
    platformProduct: BillingProductV2Type
    trialPackageName?: string
}): JSX.Element => {
    return (
        <div className="relative flex flex-col items-center">
            {/* Superman Hog floating animation */}
            <div className="w-24 h-24 animate-float">
                <SupermanHog className="w-full h-full object-contain" />
            </div>

            <div className="w-full max-w-4xl mt-2">
                <div className="text-center mb-6">
                    {trialPackageName ? (
                        <>
                            <h3 className="text-xl font-bold mb-1">You're on a trial of {trialPackageName}</h3>
                            <p className="text-gray-700 dark:text-gray-400 mb-0">
                                Enjoy your trial — cancel anytime before it ends, or explore the other packages below.
                            </p>
                        </>
                    ) : (
                        <>
                            <h3 className="text-xl font-bold mb-1">
                                You're signed up! Now level up with a platform package
                            </h3>
                            <p className="text-gray-700 dark:text-gray-400 mb-0">
                                Start a free trial of a platform package — cancel anytime, with no charge until it ends.
                            </p>
                        </>
                    )}
                </div>
                <PlatformAddonComparison product={platformProduct} />
            </div>
        </div>
    )
}
