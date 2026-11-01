import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { aiCreditsLogic, settingAmount } from './aiCreditsLogic'
import { AICreditsTile } from './AICreditsTile'
import { AISpendSummary, spendLimitOutlook } from './aiSpend'

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

export function SpendThisPeriodTile(): JSX.Element {
    const { spendSummary, spendUnavailable, settings } = useValues(aiCreditsLogic)
    const { openSettingsModal } = useActions(aiCreditsLogic)

    const limitUsd = settings?.monthly_spend_limit_usd ? Number(settings.monthly_spend_limit_usd) : null
    const outlook = spendSummary && limitUsd !== null ? spendLimitOutlook(spendSummary, limitUsd, dayjs()) : null
    const resets = spendSummary?.periodEnd.format('MMM D')

    return (
        <AICreditsTile
            label="Spend this period"
            value={spendUnavailable ? '–' : spendSummary ? humanFriendlyCurrency(spendSummary.spendUsd) : null}
            suffix={spendSummary && limitUsd !== null ? `of ${settingAmount(limitUsd)} limit` : undefined}
            footer={
                <>
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <span className="text-sm font-semibold">Organization spend limit</span>
                        <span className="text-sm text-secondary">
                            {limitUsd !== null ? `${settingAmount(limitUsd)} per billing period` : 'No limit'}
                        </span>
                        {outlook?.reached ? (
                            <span className="text-xs font-medium text-danger">
                                Spend reached the limit, so AI products are paused until {resets}
                            </span>
                        ) : outlook?.date ? (
                            <span className="text-xs font-medium text-warning-dark">
                                At this pace, spend reaches it around {outlook.date.format('MMM D')}
                            </span>
                        ) : outlook ? (
                            <span className="text-xs text-tertiary">At this pace, spend stays under it</span>
                        ) : null}
                    </div>
                    <Link
                        onClick={openSettingsModal}
                        className="text-sm font-medium"
                        data-attr="ai-credits-edit-spend-limit"
                    >
                        Edit
                    </Link>
                </>
            }
        >
            {spendSummary && limitUsd !== null && (
                <div className="flex h-1.5 rounded-full bg-fill-tertiary">
                    <div
                        className={outlook?.reached ? 'rounded-full bg-danger' : 'rounded-full bg-ai'}
                        // The bar's width is the share of the limit spent, which no utility class can hold.
                        style={{ width: `${Math.min((spendSummary.spendUsd / Math.max(limitUsd, 0.01)) * 100, 100)}%` }}
                    />
                </div>
            )}
            {spendUnavailable ? (
                <span className="text-sm text-tertiary">Spend isn't available right now</span>
            ) : (
                spendSummary && (
                    <span className="pt-1 text-sm text-tertiary">
                        {spendSummary.changeFromPrevious === null ? (
                            `Resets ${resets}`
                        ) : (
                            <>
                                <ChangeFromPrevious summary={spendSummary} />
                                resets {resets}
                            </>
                        )}
                    </span>
                )
            )}
        </AICreditsTile>
    )
}
