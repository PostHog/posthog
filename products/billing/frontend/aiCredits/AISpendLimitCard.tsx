import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { aiCreditsLogic } from './aiCreditsLogic'

export function AISpendLimitCard(): JSX.Element {
    const { settings, settingsLoading } = useValues(aiCreditsLogic)
    const { openSettingsModal } = useActions(aiCreditsLogic)

    const limit = settings?.monthly_spend_limit_usd

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="m-0">Organization spend limit</h3>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={openSettingsModal}
                    data-attr="ai-credits-edit-spend-limit"
                >
                    Edit
                </LemonButton>
            </div>
            {settingsLoading && !settings ? (
                <LemonSkeleton repeat={2} />
            ) : (
                <>
                    <span>{limit ? `${humanFriendlyCurrency(limit)} per billing period` : 'No limit'}</span>
                    <span className="text-secondary">
                        The most your organization can spend on AI in a billing period.
                    </span>
                </>
            )}
        </LemonCard>
    )
}
