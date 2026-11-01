import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { billingLogic } from 'lib/logic/billing/billingLogic'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { aiCreditsLogic, cardShortLabel, settingAmount } from './aiCreditsLogic'
import { AICreditsTile } from './AICreditsTile'
import { balanceRunwayDays } from './aiSpend'

export function BalanceTile(): JSX.Element {
    const {
        spend,
        spendSummary,
        spendUnavailable,
        settings,
        settingsLoading,
        card,
        history,
        pendingUsd,
        reloadedThisPeriodUsd,
    } = useValues(aiCreditsLogic)
    const { openSettingsModal } = useActions(aiCreditsLogic)
    const { billing } = useValues(billingLogic)

    const balanceUsd = spend ? Number(spend.balance_usd) : null
    const thresholdUsd = settings?.low_balance_threshold_usd ? Number(settings.low_balance_threshold_usd) : null
    const reload = settings?.automatic_reload
    const cardOnFile = card?.card ?? null
    const everFunded = (history?.results.length ?? 0) > 0
    const runwayDays =
        balanceUsd !== null && spendSummary ? balanceRunwayDays(balanceUsd, spendSummary.dailyAverageUsd) : null

    const valueClassName =
        balanceUsd === null
            ? undefined
            : balanceUsd <= 0 && everFunded
              ? 'text-danger'
              : thresholdUsd !== null && balanceUsd > 0 && balanceUsd < thresholdUsd
                ? 'text-warning-dark'
                : undefined

    const runway =
        runwayDays === null
            ? null
            : runwayDays < 1
              ? 'Less than a day at current spend'
              : `About ${pluralize(runwayDays, 'day')} at current spend`
    const pending = pendingUsd > 0 ? `+${humanFriendlyCurrency(pendingUsd)} pending` : null
    const note =
        balanceUsd === null
            ? null
            : [balanceUsd <= 0 ? (everFunded ? 'Add funds to keep using AI' : 'Nothing added yet') : runway, pending]
                  .filter(Boolean)
                  .join(' · ') || null

    const disabledOn = reload?.disabled_at ? dayjs(reload.disabled_at).format('MMM D') : null
    const declined =
        reload?.disabled_reason === 'card_declined'
            ? `${cardOnFile ? cardShortLabel(cardOnFile) : 'Your card'} declined ${disabledOn}`
            : reload?.disabled_reason === 'authentication_required'
              ? `Your bank wanted to approve a reload ${disabledOn}`
              : reload?.disabled_reason === 'no_card'
                ? `No card on file for a reload ${disabledOn}`
                : null

    const edit = (
        <Link onClick={openSettingsModal} className="text-sm font-medium" data-attr="ai-credits-edit-reload">
            Edit
        </Link>
    )

    return (
        <AICreditsTile
            label="Balance"
            value={spendUnavailable ? '–' : balanceUsd !== null ? humanFriendlyCurrency(balanceUsd) : null}
            valueClassName={valueClassName}
            footerClassName={declined ? 'bg-danger-highlight' : undefined}
            footer={
                settingsLoading && !settings ? (
                    <LemonSkeleton repeat={2} className="flex-1" />
                ) : declined ? (
                    <>
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <span className="text-sm font-semibold text-danger">Automatic reload is off</span>
                            <span className="text-sm text-danger">{declined}</span>
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
                        {edit}
                    </>
                ) : (
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
                            <span className="text-sm text-secondary">
                                {reload?.enabled && thresholdUsd !== null && reload.target_usd
                                    ? `Below ${settingAmount(thresholdUsd)}, reload to ${settingAmount(reload.target_usd)}` +
                                      (cardOnFile ? ` · ${cardShortLabel(cardOnFile)}` : '')
                                    : 'Add credits when the balance runs low'}
                            </span>
                            {reload?.enabled && reloadedThisPeriodUsd !== null && (
                                <span className="text-xs text-tertiary">
                                    {reload.monthly_reload_limit_usd
                                        ? `${settingAmount(reloadedThisPeriodUsd)} of ${settingAmount(reload.monthly_reload_limit_usd)} reloaded this period`
                                        : `${settingAmount(reloadedThisPeriodUsd)} reloaded this period`}
                                </span>
                            )}
                        </div>
                        {edit}
                    </>
                )
            }
        >
            {spendUnavailable ? (
                <span className="text-sm text-tertiary">The balance isn't available right now</span>
            ) : (
                note && <span className="text-sm text-tertiary">{note}</span>
            )}
        </AICreditsTile>
    )
}
