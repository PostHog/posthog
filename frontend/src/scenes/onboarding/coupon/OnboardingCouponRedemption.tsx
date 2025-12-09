import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CouponRedemption } from 'scenes/coupons/CouponRedemption'
import { parseCouponCampaign } from 'scenes/coupons/utils'
import { getOnboardingEntryUrl } from 'scenes/onboarding/utils'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: OnboardingCouponRedemption,
}

export function OnboardingCouponRedemption(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const campaign = parseCouponCampaign(router.values.currentLocation.pathname) || ''

    const continueToOnboarding = (): void => {
        router.actions.push(getOnboardingEntryUrl(featureFlags))
    }

    return (
        <div className="flex flex-col items-center justify-center min-h-screen p-4 bg-primary">
            <CouponRedemption
                campaign={campaign}
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
