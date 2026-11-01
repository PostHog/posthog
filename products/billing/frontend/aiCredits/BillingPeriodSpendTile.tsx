import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { aiCreditsLogic, settingAmount } from './aiCreditsLogic'
import { AICreditsTile } from './AICreditsTile'
import { AISpendSummary, SpendLimitOutlook, spendLimitOutlook } from './aiSpend'

function ChangeFromPrevious({ change, before }: { change: number; before: string }): JSX.Element {
    const percent = Math.round(change * 100)
    if (percent === 0) {
        return <>Level with {before} · </>
    }
    return (
        <>
            <span className={percent > 0 ? 'text-danger' : 'text-success'}>
                {percent > 0 ? '↗' : '↘'} {Math.abs(percent)}%
            </span>{' '}
            vs {before} ·{' '}
        </>
    )
}

function PeriodLine({ summary, isCurrentPeriod }: { summary: AISpendSummary; isCurrentPeriod: boolean }): JSX.Element {
    const end = isCurrentPeriod
        ? `resets ${summary.periodEnd.format('MMM D')}`
        : `ended ${summary.periodEnd.subtract(1, 'day').format('MMM D')}`
    if (summary.changeFromPrevious === null) {
        return <span className="pt-1 text-sm text-tertiary">{end.charAt(0).toUpperCase() + end.slice(1)}</span>
    }
    return (
        <span className="pt-1 text-sm text-tertiary">
            <ChangeFromPrevious
                change={summary.changeFromPrevious}
                before={isCurrentPeriod ? 'last period' : 'the period before'}
            />
            {end}
        </span>
    )
}

function OutlookNote({ outlook, resets }: { outlook: SpendLimitOutlook; resets: string }): JSX.Element {
    if (outlook.reached) {
        return (
            <span className="text-xs font-medium text-danger">
                Spend reached the limit, so AI products are paused until {resets}
            </span>
        )
    }
    if (outlook.date) {
        return (
            <span className="text-xs font-medium text-warning-dark">
                At this pace, spend reaches it around {outlook.date.format('MMM D')}
            </span>
        )
    }
    return <span className="text-xs text-tertiary">At this pace, spend stays under it</span>
}

function LimitBar({
    spendUsd,
    limitUsd,
    reached,
}: {
    spendUsd: number
    limitUsd: number
    reached: boolean
}): JSX.Element {
    return (
        <div className="flex h-1.5 rounded-full bg-fill-tertiary">
            <div
                className={reached ? 'rounded-full bg-danger' : 'rounded-full bg-ai'}
                // The bar's width is the share of the limit spent, which no utility class can hold.
                style={{ width: `${Math.min((spendUsd / Math.max(limitUsd, 0.01)) * 100, 100)}%` }}
            />
        </div>
    )
}

/** The limit is a setting for the current period, so the footer describes the current period whichever one the tile shows. */
function SpendLimitFooter({
    limitUsd,
    outlook,
}: {
    limitUsd: number | null
    outlook: SpendLimitOutlook | null
}): JSX.Element {
    const { currentSpendSummary } = useValues(aiCreditsLogic)
    const { openSettingsModal } = useActions(aiCreditsLogic)
    return (
        <>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="text-sm font-semibold">Organization spend limit</span>
                <span className="text-sm text-secondary">
                    {limitUsd !== null ? `${settingAmount(limitUsd)} per billing period` : 'No limit'}
                </span>
                {outlook && currentSpendSummary && (
                    <OutlookNote outlook={outlook} resets={currentSpendSummary.periodEnd.format('MMM D')} />
                )}
            </div>
            <Link onClick={openSettingsModal} className="text-sm font-medium" data-attr="ai-credits-edit-spend-limit">
                Edit
            </Link>
        </>
    )
}

function SpendDetails({
    limitUsd,
    outlook,
}: {
    limitUsd: number | null
    outlook: SpendLimitOutlook | null
}): JSX.Element | null {
    const { spendSummary, spendUnavailable, isCurrentPeriod } = useValues(aiCreditsLogic)
    if (spendUnavailable) {
        return <span className="text-sm text-tertiary">Spend isn't available right now</span>
    }
    if (!spendSummary) {
        return null
    }
    return (
        <>
            {isCurrentPeriod && limitUsd !== null && (
                <LimitBar spendUsd={spendSummary.spendUsd} limitUsd={limitUsd} reached={!!outlook?.reached} />
            )}
            <PeriodLine summary={spendSummary} isCurrentPeriod={isCurrentPeriod} />
        </>
    )
}

export function BillingPeriodSpendTile(): JSX.Element {
    const { spendSummary, spendUnavailable, currentSpendSummary, isCurrentPeriod, settings } = useValues(aiCreditsLogic)

    const limitUsd = settings?.monthly_spend_limit_usd ? Number(settings.monthly_spend_limit_usd) : null
    const outlook =
        currentSpendSummary && limitUsd !== null ? spendLimitOutlook(currentSpendSummary, limitUsd, dayjs()) : null

    return (
        <AICreditsTile
            label={isCurrentPeriod ? 'Spend this period' : 'Spend'}
            amountUsd={spendSummary?.spendUsd ?? null}
            unavailable={spendUnavailable}
            suffix={
                isCurrentPeriod && spendSummary && limitUsd !== null ? `of ${settingAmount(limitUsd)} limit` : undefined
            }
            footer={<SpendLimitFooter limitUsd={limitUsd} outlook={outlook} />}
        >
            <SpendDetails limitUsd={limitUsd} outlook={outlook} />
        </AICreditsTile>
    )
}
