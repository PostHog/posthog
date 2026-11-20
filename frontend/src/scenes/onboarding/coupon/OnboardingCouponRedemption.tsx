import { router } from 'kea-router'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cheatCodeCampaignSlug } from 'lib/components/CheatCodes/cheatCodeCampaignSlug'
import { CheatCodeRedemption } from 'scenes/coupons/CheatCodeRedemption'
import { CouponRedemption } from 'scenes/coupons/CouponRedemption'
import { parseCouponCampaign } from 'scenes/coupons/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: OnboardingCouponRedemption,
}

export function OnboardingCouponRedemption(): JSX.Element {
    const campaign = parseCouponCampaign(router.values.currentLocation.pathname) || ''

    const continueToOnboarding = (): void => {
        router.actions.push(urls.onboarding())
    }

    const cheatCodeSlug = cheatCodeCampaignSlug(campaign)

    const renderSuccessActions = (): JSX.Element => (
        <LemonButton type="primary" status="alt" sideIcon={<IconArrowRight />} onClick={continueToOnboarding}>
            Continue to setup
        </LemonButton>
    )
    const renderFooter = (): JSX.Element => (
        <LemonButton type="secondary" onClick={continueToOnboarding}>
            Skip for now
        </LemonButton>
    )

    return (
        <div className="flex flex-col items-center justify-center min-h-screen p-4 bg-primary">
            {cheatCodeSlug ? (
                <CheatCodeRedemption
                    campaignSlug={cheatCodeSlug}
                    renderSuccessActions={renderSuccessActions}
                    renderFooter={renderFooter}
                />
            ) : (
                <CouponRedemption
                    campaign={campaign}
                    renderSuccessActions={renderSuccessActions}
                    renderFooter={renderFooter}
                />
            )}
        </div>
    )
}
