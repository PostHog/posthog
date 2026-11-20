import { useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { urls } from 'scenes/urls'

import { HotKey } from '~/types'

import { couponLogic } from './couponLogic'

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
    const alreadyClaimed = !!getClaimedCouponForCampaign(campaignSlug)
    const keys = campaignSlug.toLowerCase().split('') as HotKey[]

    return (
        <div className="mx-auto w-full max-w-160 mt-8 px-4">
            <div className="bg-surface-secondary rounded-lg p-6 space-y-4">
                {couponsOverviewLoading ? (
                    <div className="flex items-center gap-2">
                        <Spinner className="text-lg" />
                        <span>Checking the cheat code</span>
                    </div>
                ) : alreadyClaimed ? (
                    <div className="space-y-4">
                        <div className="flex items-center gap-2 text-success">
                            <IconCheck className="shrink-0" />
                            <span>Your organization already used this cheat code.</span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            {renderSuccessActions ? (
                                renderSuccessActions()
                            ) : (
                                <LemonButton type="primary" to={urls.organizationBilling()} disableClientSideRouting>
                                    View in billing
                                </LemonButton>
                            )}
                        </div>
                    </div>
                ) : (
                    <>
                        <h2 className="text-xl">Type the cheat code anywhere in PostHog</h2>
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
