import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { billingLogic } from 'lib/logic/billing/billingLogic'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AIAutomaticReloadSettingsApi, AICreditCardApi } from 'products/billing/frontend/generated/api.schemas'

import { aiCreditsLogic, cardShortLabel, settingAmount } from './aiCreditsLogic'
import { AICreditsTile } from './AICreditsTile'
import { balanceRunwayDays } from './aiSpend'

function balanceClassName(balanceUsd: number, thresholdUsd: number | null, everFunded: boolean): string | undefined {
    if (balanceUsd <= 0) {
        return everFunded ? 'text-danger' : undefined
    }
    return thresholdUsd !== null && balanceUsd < thresholdUsd ? 'text-warning-dark' : undefined
}

function balanceNote(balanceUsd: number, runwayDays: number | null, pendingUsd: number, everFunded: boolean): string {
    const notes: string[] = []
    if (balanceUsd <= 0) {
        notes.push(everFunded ? 'Add funds to keep using AI' : 'Nothing added yet')
    } else if (runwayDays !== null) {
        notes.push(
            runwayDays < 1
                ? 'Less than a day at current spend'
                : `About ${pluralize(runwayDays, 'day')} at current spend`
        )
    }
    if (pendingUsd > 0) {
        notes.push(`+${humanFriendlyCurrency(pendingUsd)} pending`)
    }
    return notes.join(' · ')
}

const DECLINED_MESSAGES: Record<string, (card: string) => string> = {
    card_declined: (card) => `${card} declined`,
    authentication_required: () => 'Your bank wanted to approve a reload',
    no_card: () => 'No card on file for a reload',
}

function declinedMessage(
    reload: AIAutomaticReloadSettingsApi | undefined,
    card: AICreditCardApi | null
): string | null {
    const message = reload?.disabled_reason ? DECLINED_MESSAGES[reload.disabled_reason] : undefined
    if (!message) {
        return null
    }
    const on = reload?.disabled_at ? ` ${dayjs(reload.disabled_at).format('MMM D')}` : ''
    return `${message(card ? cardShortLabel(card) : 'Your card')}${on}`
}

function EditLink(): JSX.Element {
    const { openSettingsModal } = useActions(aiCreditsLogic)
    return (
        <Link onClick={openSettingsModal} className="text-sm font-medium" data-attr="ai-credits-edit-reload">
            Edit
        </Link>
    )
}

function DeclinedFooter({ message }: { message: string }): JSX.Element {
    const { billing } = useValues(billingLogic)
    return (
        <>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="text-sm font-semibold text-danger">Automatic reload is off</span>
                <span className="text-sm text-danger">{message}</span>
            </div>
            {billing?.stripe_portal_url && (
                <LemonButton
                    type="secondary"
                    size="small"
                    to={billing.stripe_portal_url}
                    targetBlank
                    data-attr="ai-credits-update-card"
                >
                    Update card
                </LemonButton>
            )}
            <EditLink />
        </>
    )
}

function ReloadFooter(): JSX.Element {
    const { settings, card, reloadedThisPeriodText } = useValues(aiCreditsLogic)
    const reload = settings?.automatic_reload
    const threshold = settings?.low_balance_threshold_usd
    const cardOnFile = card?.card
    const summary =
        reload?.enabled && threshold && reload.target_usd
            ? `Below ${settingAmount(threshold)}, reload to ${settingAmount(reload.target_usd)}` +
              (cardOnFile ? ` · ${cardShortLabel(cardOnFile)}` : '')
            : 'Add credits when the balance runs low'
    return (
        <>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">Automatic reload</span>
                    {reload && (
                        <LemonTag type={reload.enabled ? 'success' : 'default'} size="small">
                            {reload.enabled ? 'On' : 'Off'}
                        </LemonTag>
                    )}
                </div>
                <span className="text-sm text-secondary">{summary}</span>
                {reload?.enabled && reloadedThisPeriodText && (
                    <span className="text-xs text-tertiary">{reloadedThisPeriodText}</span>
                )}
            </div>
            <EditLink />
        </>
    )
}

function BalanceNote(): JSX.Element | null {
    const { spend, spendSummary, spendUnavailable, history, pendingUsd } = useValues(aiCreditsLogic)
    if (spendUnavailable) {
        return <span className="text-sm text-tertiary">The balance isn't available right now</span>
    }
    if (!spend || !spendSummary) {
        return null
    }
    const balanceUsd = Number(spend.balance_usd)
    const runwayDays = balanceRunwayDays(balanceUsd, spendSummary.dailyAverageUsd)
    const note = balanceNote(balanceUsd, runwayDays, pendingUsd, (history?.results.length ?? 0) > 0)
    return note ? <span className="text-sm text-tertiary">{note}</span> : null
}

export function BalanceTile(): JSX.Element {
    const { spend, spendUnavailable, settings, settingsLoading, card, history } = useValues(aiCreditsLogic)

    const balanceUsd = spend ? Number(spend.balance_usd) : null
    const thresholdUsd = settings?.low_balance_threshold_usd ? Number(settings.low_balance_threshold_usd) : null
    const declined = declinedMessage(settings?.automatic_reload, card?.card ?? null)

    return (
        <AICreditsTile
            label="Balance"
            amountUsd={balanceUsd}
            unavailable={spendUnavailable}
            valueClassName={
                balanceUsd !== null
                    ? balanceClassName(balanceUsd, thresholdUsd, (history?.results.length ?? 0) > 0)
                    : undefined
            }
            footerClassName={declined ? 'bg-danger-highlight' : undefined}
            footer={
                settingsLoading && !settings ? (
                    <LemonSkeleton repeat={2} className="flex-1" />
                ) : declined ? (
                    <DeclinedFooter message={declined} />
                ) : (
                    <ReloadFooter />
                )
            }
        >
            <BalanceNote />
        </AICreditsTile>
    )
}
