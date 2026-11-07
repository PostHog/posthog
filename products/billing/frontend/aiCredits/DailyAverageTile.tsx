import { useValues } from 'kea'

import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { aiCreditsLogic } from './aiCreditsLogic'
import { AICreditsTile } from './AICreditsTile'

export function DailyAverageTile(): JSX.Element {
    const { spendSummary, spendUnavailable, isCurrentPeriod } = useValues(aiCreditsLogic)

    return (
        <AICreditsTile
            label="Average per day"
            amountUsd={spendSummary?.dailyAverageUsd ?? null}
            unavailable={spendUnavailable}
            footer={
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="text-sm font-semibold">Busiest day</span>
                    <span className="text-sm text-secondary">
                        {spendUnavailable
                            ? '–'
                            : spendSummary?.busiestDay
                              ? `${spendSummary.busiestDay.date.format('MMM D')} · ${humanFriendlyCurrency(spendSummary.busiestDay.spendUsd)}`
                              : 'No spend yet'}
                    </span>
                    {spendSummary?.previousDailyAverageUsd !== null &&
                        spendSummary?.previousDailyAverageUsd !== undefined && (
                            <span className="text-xs text-tertiary">
                                {isCurrentPeriod ? 'Last period' : 'The period before'} averaged{' '}
                                {humanFriendlyCurrency(spendSummary.previousDailyAverageUsd)} a day
                            </span>
                        )}
                </div>
            }
        >
            {spendSummary && (
                <span className="text-sm text-tertiary">
                    {spendSummary.productsWithSpend > 0
                        ? `Across ${pluralize(spendSummary.productsWithSpend, 'AI product')}`
                        : 'No AI spend in this period'}
                </span>
            )}
        </AICreditsTile>
    )
}
