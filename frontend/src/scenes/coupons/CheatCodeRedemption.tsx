import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { couponLogic } from './couponLogic'

interface CheatCodeRedemptionProps {
    campaignSlug: string
    /** Replaces the default "View in billing" buttons once the code is used. */
    renderSuccessActions?: () => React.ReactNode
    /** Extra content under the claim button, such as the onboarding skip button. */
    renderFooter?: () => React.ReactNode
}

export function CheatCodeRedemption({
    campaignSlug,
    renderSuccessActions,
    renderFooter,
}: CheatCodeRedemptionProps): JSX.Element {
    const logic = couponLogic({ campaign: campaignSlug })
    const { cheatCodeClaim, cheatCodeClaimLoading, couponsOverviewLoading, getClaimedCouponForCampaign } =
        useValues(logic)
    const { claimCheatCodeCampaign } = useActions(logic)

    const claimed = cheatCodeClaim === 'claimed'
    const alreadyClaimed = cheatCodeClaim === 'already_claimed' || !!getClaimedCouponForCampaign(campaignSlug)

    const successActions = renderSuccessActions ? (
        renderSuccessActions()
    ) : (
        <div className="flex flex-wrap gap-2">
            <LemonButton type="primary" to={urls.organizationBilling()} disableClientSideRouting>
                View in billing
            </LemonButton>
            <LemonButton type="secondary" to={urls.projectHomepage()} disableClientSideRouting>
                Return to PostHog
            </LemonButton>
        </div>
    )

    return (
        <div className="mx-auto w-full max-w-160 mt-8 px-4">
            <div className="bg-surface-secondary rounded-lg p-6 space-y-4">
                <div>
                    <h2 className="text-xl mb-2">
                        Cheat code: <span className="font-mono">{campaignSlug.toUpperCase()}</span>
                    </h2>
                    <p className="text-muted">
                        Adds $5 of credit to your organization. Each organization can use it once.
                    </p>
                </div>

                {couponsOverviewLoading ? (
                    <div className="flex items-center gap-2">
                        <Spinner className="text-lg" />
                        <span>Checking the cheat code</span>
                    </div>
                ) : claimed ? (
                    <div className="space-y-4">
                        <div className="flex items-center gap-2 text-success">
                            <IconCheck className="shrink-0" />
                            <span>Cheat code used. $5 of credit was added.</span>
                        </div>
                        {successActions}
                    </div>
                ) : alreadyClaimed ? (
                    <div className="space-y-4">
                        <div className="flex items-center gap-2 text-success">
                            <IconCheck className="shrink-0" />
                            <span>Your organization already used this cheat code.</span>
                        </div>
                        {successActions}
                    </div>
                ) : (
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="primary"
                            onClick={() => claimCheatCodeCampaign(campaignSlug)}
                            loading={cheatCodeClaimLoading}
                            disabledReason={cheatCodeClaimLoading ? 'Claiming the credit' : undefined}
                            data-attr="cheat-code-claim"
                        >
                            Claim $5 credit
                        </LemonButton>
                        {renderFooter?.()}
                    </div>
                )}
            </div>
        </div>
    )
}
