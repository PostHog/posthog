import { useValues } from 'kea'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { SupermanHog } from 'lib/components/hedgehogs'
import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { PlatformAddonComparison } from 'scenes/billing/PlatformAddonComparison'

import { ProductKey } from '~/queries/schema/schema-general'
import { type BillingProductV2Type, OnboardingStepKey } from '~/types'

import { OnboardingStepComponentType } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import PlanCards from './PlanCards'

type OnboardingUpgradeStepProps = {
    product: BillingProductV2Type
}

export const OnboardingUpgradeStep: OnboardingStepComponentType<OnboardingUpgradeStepProps> = ({ product }) => {
    const { billingLoading } = useValues(billingLogic)

    if (billingLoading) {
        return (
            <div className="flex items-center justify-center my-20">
                <Spinner className="text-2xl text-muted w-10 h-10" />
            </div>
        )
    }

    return (
        <OnboardingStep title="Select a plan" stepKey={OnboardingStepKey.PLANS} showContinue={!!product.subscribed}>
            {!product.subscribed && <PlanCards product={product} />}
            {product.subscribed && <ProductSubscribed product={product} />}
        </OnboardingStep>
    )
}
OnboardingUpgradeStep.stepKey = OnboardingStepKey.PLANS

const ProductSubscribed = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { billing } = useValues(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const platformProduct = billing?.products?.find((p) => p.type === ProductKey.PLATFORM_AND_SUPPORT)
    const showPlatformPackages = featureFlags[FEATURE_FLAGS.ONBOARDING_PLATFORM_PACKAGES] === 'test' && platformProduct

    // Split into two components so the hogfetti hook (and its window resize listener) only mounts on
    // the celebration screen — the packages variant reloads the page on every billing action and
    // would re-fire confetti each time, so it doesn't use it.
    if (!showPlatformPackages) {
        return <SubscribedCelebration product={product} />
    }
    return <PlatformPackagesUpsell platformProduct={platformProduct} />
}

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

const PlatformPackagesUpsell = ({ platformProduct }: { platformProduct: BillingProductV2Type }): JSX.Element => {
    // Only state a specific length in the header when every trialable package shares it; otherwise stay
    // generic (each package card still shows its own exact trial length). Trial lengths come from billing.
    const trialLengths = new Set(
        (platformProduct.addons ?? [])
            .map((addon) => addon.trial?.length)
            .filter((length): length is number => length != null)
    )
    const sharedTrialLength = trialLengths.size === 1 ? [...trialLengths][0] : null

    return (
        <div className="relative flex flex-col items-center">
            {/* Superman Hog floating animation */}
            <div className="w-24 h-24 animate-float">
                <SupermanHog className="w-full h-full object-contain" />
            </div>

            <div className="w-full max-w-4xl mt-2">
                <div className="text-center mb-6">
                    <h3 className="text-xl font-bold mb-1">You're signed up! Now level up with a platform package</h3>
                    <p className="text-gray-700 dark:text-gray-400 mb-0">
                        Start a free {sharedTrialLength ? `${sharedTrialLength}-day ` : ''}trial of any package — cancel
                        anytime, with no charge until it ends.
                    </p>
                </div>
                <PlatformAddonComparison product={platformProduct} />
            </div>
        </div>
    )
}
