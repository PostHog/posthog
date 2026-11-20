import { useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { CheatCodeClaimOutcome, cheatCodeLogic } from 'lib/components/CheatCodes/cheatCodeLogic'
import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { HotKey } from '~/types'

import { couponLogic } from './couponLogic'

// The shortcut stays silent about these refusals elsewhere, so only this page explains them.
const REFUSAL_MESSAGES: Partial<Record<CheatCodeClaimOutcome, string>> = {
    campaign_full: 'Too late! All the credit for this cheat code has been claimed.',
    card_already_used: 'This card was already used to claim the cheat code in another organization.',
}

interface CheatCodeRedemptionProps {
    campaignSlug: string
    renderSuccessActions?: () => React.ReactNode
    renderFooter?: () => React.ReactNode
}

export function CheatCodeRedemption({
    campaignSlug,
    renderSuccessActions,
    renderFooter,
}: CheatCodeRedemptionProps): JSX.Element {
    const { couponsOverviewLoading, getClaimedCouponForCampaign } = useValues(couponLogic({ campaign: campaignSlug }))
    const { claimOutcomes } = useValues(cheatCodeLogic)
    const outcome = claimOutcomes[campaignSlug]
    const alreadyClaimed = outcome === 'already_claimed' || !!getClaimedCouponForCampaign(campaignSlug)
    const refusalMessage = outcome ? REFUSAL_MESSAGES[outcome] : undefined
    const keys = campaignSlug.toLowerCase().split('') as HotKey[]

    const successActions = (
        <div className="flex flex-wrap gap-2">
            {renderSuccessActions ? (
                renderSuccessActions()
            ) : (
                <LemonButton type="primary" to={urls.organizationBilling()} disableClientSideRouting>
                    View in billing
                </LemonButton>
            )}
        </div>
    )

    return (
        <div className="mx-auto w-full max-w-160 mt-8 px-4">
            <div className="bg-surface-secondary rounded-lg p-6 space-y-4">
                {outcome === 'claimed' ? (
                    <div className="space-y-4">
                        <div className="flex items-center gap-2 text-success">
                            <IconCheck className="shrink-0" />
                            <span>Cheat code activated. $5 of credit was added to your organization.</span>
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
                ) : couponsOverviewLoading ? (
                    <div className="flex items-center gap-2">
                        <Spinner className="text-lg" />
                        <span>Checking the cheat code</span>
                    </div>
                ) : (
                    <>
                        <h2 className="text-xl">Type the cheat code anywhere in PostHog</h2>
                        {refusalMessage && <LemonBanner type="warning">{refusalMessage}</LemonBanner>}
                        <p className="text-muted">
                            Like in GTA: San Andreas, there's no box to enter it in. Type these keys while PostHog is
                            open, on this page or any other, and $5 of credit goes to your organization. Each
                            organization can use it once.
                        </p>
                        <p className="text-muted">
                            Heads up: you need billing set up with a card on file. Pay-as-you-go counts.
                        </p>
                        <div className="flex flex-wrap gap-2" translate="no" data-attr="cheat-code-keys">
                            {keys.map((key, index) => (
                                <KeyboardShortcut key={index} {...{ [key]: true }} className="h-10 min-w-10 text-lg" />
                            ))}
                        </div>
                        {renderFooter?.()}
                    </>
                )}
            </div>
        </div>
    )
}
