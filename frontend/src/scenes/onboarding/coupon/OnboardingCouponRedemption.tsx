import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CouponRedemption } from 'scenes/coupons/CouponRedemption'
import { campaignConfigs } from 'scenes/coupons/campaigns'
import { getOnboardingEntryUrl } from 'scenes/onboarding/utils'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: OnboardingCouponRedemption,
}

export function OnboardingCouponRedemption(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    // Get campaign from URL path (handles optional /project/:id/ prefix)
    const match = router.values.currentLocation.pathname.match(/\/onboarding\/coupons\/([^/?]+)/)
    const campaign = match?.[1] || ''
    const config = campaignConfigs[campaign]

    const continueToOnboarding = (): void => {
        // Don't pass the coupon `next` param - let normal onboarding flow determine the final redirect
        router.actions.push(getOnboardingEntryUrl(featureFlags))
    }

    if (!config) {
        return (
            <div className="flex flex-col items-center justify-center min-h-screen p-4 bg-primary">
                <LemonBanner type="error" className="max-w-lg">
                    <h2 className="mb-2">Invalid campaign</h2>
                    <p>{campaign ? `The campaign "${campaign}" was not found.` : 'No campaign specified.'}</p>
                    <LemonButton type="primary" onClick={continueToOnboarding} className="mt-4">
                        Continue to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-center justify-center min-h-screen p-4 bg-primary">
            <CouponRedemption
                campaign={campaign}
                config={config}
                renderSuccessActions={() => (
                    <LemonButton
                        type="primary"
                        status="alt"
                        sideIcon={<IconArrowRight />}
                        onClick={continueToOnboarding}
                    >
                        Continue to setup
                    </LemonButton>
                )}
                renderFooter={() => (
                    <LemonButton type="secondary" onClick={continueToOnboarding}>
                        Skip for now
                    </LemonButton>
                )}
            />
        </div>
    )
}
