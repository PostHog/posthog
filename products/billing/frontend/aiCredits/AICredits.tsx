import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { billingLogic } from 'lib/logic/billing/billingLogic'

import { AddAICreditsModal } from './AddAICreditsModal'
import { AICreditHistory } from './AICreditHistory'
import { aiCreditsLogic } from './aiCreditsLogic'
import { AISpendLimitCard } from './AISpendLimitCard'
import { AISpendSettingsModal } from './AISpendSettingsModal'
import { AutomaticReloadCard } from './AutomaticReloadCard'

const DISABLED_REASONS: Record<string, string> = {
    card_declined: 'your bank declined the card',
    authentication_required: 'your bank asked to authenticate the payment',
    no_card: 'there was no card on file',
}

export function AICredits(): JSX.Element {
    const { settings, unavailable } = useValues(aiCreditsLogic)
    const { openAddFundsModal, openSettingsModal } = useActions(aiCreditsLogic)
    const { billing } = useValues(billingLogic)

    if (unavailable) {
        return <LemonBanner type="info">AI credits aren't available for this organization yet.</LemonBanner>
    }

    const disabledReason = settings?.automatic_reload.disabled_reason
    const disabledAt = settings?.automatic_reload.disabled_at

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="m-0 text-secondary">Prepaid AI credits pay for PostHog's AI products.</p>
                <LemonButton type="primary" onClick={openAddFundsModal} data-attr="ai-credits-add-funds">
                    Add funds
                </LemonButton>
            </div>
            {disabledReason && (
                <LemonBanner
                    type="error"
                    action={
                        billing?.stripe_portal_url
                            ? { children: 'Update card', to: billing.stripe_portal_url, targetBlank: true }
                            : { children: 'Turn it back on', onClick: openSettingsModal }
                    }
                >
                    <span>Automatic reload turned off </span>
                    {disabledAt && <TZLabel time={disabledAt} />}
                    <span>
                        {' '}
                        because {DISABLED_REASONS[disabledReason] ?? 'the last reload failed'}. Update your card, then
                        turn automatic reload back on.
                    </span>
                </LemonBanner>
            )}
            <div className="grid gap-4 @min-[48rem]/main-content:grid-cols-2">
                <AutomaticReloadCard />
                <AISpendLimitCard />
            </div>
            <AICreditHistory />
            <AddAICreditsModal />
            <AISpendSettingsModal />
        </div>
    )
}
