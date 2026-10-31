import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { aiCreditsLogic, cardLabel } from './aiCreditsLogic'

export function AutomaticReloadCard(): JSX.Element {
    const { settings, settingsLoading, card } = useValues(aiCreditsLogic)
    const { openSettingsModal } = useActions(aiCreditsLogic)

    const reload = settings?.automatic_reload
    const cardOnFile = card?.card ?? null

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <h3 className="m-0">Automatic reload</h3>
                    {reload && (
                        <LemonTag type={reload.enabled ? 'success' : 'default'}>
                            {reload.enabled ? 'On' : 'Off'}
                        </LemonTag>
                    )}
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={openSettingsModal}
                    data-attr="ai-credits-edit-reload"
                >
                    Edit
                </LemonButton>
            </div>
            {settingsLoading && !settings ? (
                <LemonSkeleton repeat={2} />
            ) : reload?.enabled ? (
                <>
                    <span>
                        Below {humanFriendlyCurrency(settings?.low_balance_threshold_usd ?? undefined)}, reload to{' '}
                        {humanFriendlyCurrency(reload.target_usd ?? undefined)}
                        {cardOnFile ? ` with your ${cardLabel(cardOnFile)}` : ''}
                    </span>
                    <span className="text-secondary">
                        {reload.monthly_reload_limit_usd
                            ? `Up to ${humanFriendlyCurrency(reload.monthly_reload_limit_usd)} each billing period`
                            : 'No monthly limit'}
                    </span>
                </>
            ) : (
                <span className="text-secondary">
                    Turn it on to add credits when your AI balance runs low, so AI products keep working.
                </span>
            )}
        </LemonCard>
    )
}
