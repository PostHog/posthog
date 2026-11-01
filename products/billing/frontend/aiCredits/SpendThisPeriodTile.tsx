import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { aiCreditsLogic, settingAmount } from './aiCreditsLogic'
import { AICreditsTile } from './AICreditsTile'
import { AISpendSummary, SpendLimitOutlook, spendLimitOutlook } from './aiSpend'

function ChangeFromPrevious({ summary }: { summary: AISpendSummary }): JSX.Element | null {
    if (summary.changeFromPrevious === null) {
        return null
    }
    const percent = Math.round(summary.changeFromPrevious * 100)
    if (percent === 0) {
        return <>Level with last period · </>
    }
    return (
        <>
            <span className={percent > 0 ? 'text-danger' : 'text-success'}>
                {percent > 0 ? '↗' : '↘'} {Math.abs(percent)}%
            </span>{' '}
            vs last period ·{' '}
        </>
    )
}

function OutlookNote({ outlook, resets }: { outlook: SpendLimitOutlook | null; resets: string }): JSX.Element | null {
    if (!outlook) {
        return null
    }
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

function PeriodLine({ summary }: { summary: AISpendSummary }): JSX.Element {
    const resets = summary.periodEnd.format('MMM D')
    return (
        <span className="pt-1 text-sm text-tertiary">
            {summary.changeFromPrevious === null ? (
                `Resets ${resets}`
            ) : (
                <>
                    <ChangeFromPrevious summary={summary} />
                    resets {resets}
                </>
            )}
        </span>
    )
}

function SpendLimitFooter({
    limitUsd,
    outlook,
}: {
    limitUsd: number | null
    outlook: SpendLimitOutlook | null
}): JSX.Element {
    const { spendSummary } = useValues(aiCreditsLogic)
    const { openSettingsModal } = useActions(aiCreditsLogic)
    return (
        <>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="text-sm font-semibold">Organization spend limit</span>
                <span className="text-sm text-secondary">
                    {limitUsd !== null ? `${settingAmount(limitUsd)} per billing period` : 'No limit'}
                </span>
                <OutlookNote outlook={outlook} resets={spendSummary?.periodEnd.format('MMM D') ?? ''} />
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
    const { spendSummary, spendUnavailable } = useValues(aiCreditsLogic)
    if (spendUnavailable) {
        return <span className="text-sm text-tertiary">Spend isn't available right now</span>
    }
    if (!spendSummary) {
        return null
    }
    return (
        <>
            {limitUsd !== null && (
                <LimitBar spendUsd={spendSummary.spendUsd} limitUsd={limitUsd} reached={!!outlook?.reached} />
            )}
            <PeriodLine summary={spendSummary} />
        </>
    )
}

export function SpendThisPeriodTile(): JSX.Element {
    const { spendSummary, spendUnavailable, settings } = useValues(aiCreditsLogic)

    const limitUsd = settings?.monthly_spend_limit_usd ? Number(settings.monthly_spend_limit_usd) : null
    const outlook = spendSummary && limitUsd !== null ? spendLimitOutlook(spendSummary, limitUsd, dayjs()) : null

    return (
        <AICreditsTile
            label="Spend this period"
            amountUsd={spendSummary?.spendUsd ?? null}
            unavailable={spendUnavailable}
            suffix={spendSummary && limitUsd !== null ? `of ${settingAmount(limitUsd)} limit` : undefined}
            footer={<SpendLimitFooter limitUsd={limitUsd} outlook={outlook} />}
        >
            <SpendDetails limitUsd={limitUsd} outlook={outlook} />
        </AICreditsTile>
    )
}
