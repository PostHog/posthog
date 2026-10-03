import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonDialog, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import type { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import type { AICreditTopUpApi, AICreditTopUpStatusEnumApi } from 'products/billing/frontend/generated/api.schemas'

import { aiCreditsLogic } from './aiCreditsLogic'

const STATUS_TAGS: Record<AICreditTopUpStatusEnumApi, { label: string; type: LemonTagType }> = {
    awaiting_tax: { label: 'Processing', type: 'warning' },
    paid: { label: 'Processing', type: 'warning' },
    credited: { label: 'Added', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
}

const failureMessage = (reason: string | null): string =>
    reason === 'not_paid_in_full'
        ? "The payment didn't cover the full amount, so no credits were added. Contact support."
        : "The purchase didn't go through. Try again, or contact support if it keeps failing."

export function AICreditsSection(): JSX.Element | null {
    const { aiCredits, inFlightTopUp, pendingTopUpAmount, topUpResponseLoading } = useValues(aiCreditsLogic)
    const { topUp } = useActions(aiCreditsLogic)

    // Billing decides who can buy AI credits, so the section stays hidden until it answers.
    if (!aiCredits?.available) {
        return null
    }

    const topUps = aiCredits.top_ups ?? []

    const confirmTopUp = (amountUsd: number): void => {
        const amount = humanFriendlyCurrency(amountUsd, 0)
        LemonDialog.open({
            title: `Buy ${amount} of AI credits?`,
            description: `We'll charge ${amount} plus any tax to the card on file. The credits are added once the payment goes through.`,
            primaryButton: {
                children: 'Buy credits',
                onClick: () => topUp(amountUsd),
                'data-attr': 'ai-credits-top-up-confirm',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <LemonCard hoverEffect={false} className="mt-6 max-w-300 p-4 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h3 className="mb-1">AI credits</h3>
                    <p className="mb-0 text-secondary">
                        Buy credits for AI usage up front. We charge the card on file, plus any tax.
                    </p>
                </div>
                <div>
                    <div className="text-secondary text-sm">Balance</div>
                    {aiCredits.balance_usd == null ? (
                        <div className="text-secondary">Unavailable right now</div>
                    ) : (
                        <div className="text-2xl font-semibold">{humanFriendlyCurrency(aiCredits.balance_usd)}</div>
                    )}
                </div>
            </div>

            {inFlightTopUp && (
                <LemonBanner type="info">
                    <span>Your purchase of </span>
                    <span>{humanFriendlyCurrency(inFlightTopUp.amount_usd, 0)}</span>
                    <span>
                        {' '}
                        is processing. The balance updates once the payment goes through, which can take a few minutes.
                    </span>
                </LemonBanner>
            )}

            <div className="flex flex-wrap items-center gap-2">
                {(aiCredits.amounts_usd ?? []).map((amountUsd) => (
                    <LemonButton
                        key={amountUsd}
                        type="secondary"
                        loading={topUpResponseLoading && pendingTopUpAmount === amountUsd}
                        disabledReason={
                            inFlightTopUp
                                ? 'Wait for the current purchase to finish'
                                : topUpResponseLoading
                                  ? 'Starting your purchase'
                                  : undefined
                        }
                        onClick={() => confirmTopUp(amountUsd)}
                        data-attr={`ai-credits-top-up-${amountUsd}`}
                    >
                        Buy {humanFriendlyCurrency(amountUsd, 0)}
                    </LemonButton>
                ))}
            </div>

            {topUps.length > 0 && (
                <LemonTable
                    size="small"
                    dataSource={topUps}
                    rowKey="id"
                    columns={[
                        {
                            title: 'Date',
                            key: 'created_at',
                            render: (_, topUp: AICreditTopUpApi) => dayjs(topUp.created_at).format('LLL'),
                        },
                        {
                            title: 'Amount',
                            key: 'amount_usd',
                            render: (_, topUp: AICreditTopUpApi) => humanFriendlyCurrency(topUp.amount_usd),
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, topUp: AICreditTopUpApi) => (
                                <div className="flex flex-col items-start gap-1 py-1">
                                    <LemonTag type={STATUS_TAGS[topUp.status].type}>
                                        {STATUS_TAGS[topUp.status].label}
                                    </LemonTag>
                                    {topUp.status === 'failed' && (
                                        <span className="text-secondary text-xs">
                                            {failureMessage(topUp.failure_reason)}
                                        </span>
                                    )}
                                </div>
                            ),
                        },
                    ]}
                />
            )}
        </LemonCard>
    )
}
