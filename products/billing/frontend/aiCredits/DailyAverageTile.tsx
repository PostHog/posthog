import { useValues } from 'kea'

import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { aiCreditsLogic } from './aiCreditsLogic'
import { AICreditsTile } from './AICreditsTile'

export function DailyAverageTile(): JSX.Element {
    const { spendSummary, spendUnavailable } = useValues(aiCreditsLogic)

    return (
        <AICreditsTile
            label="Average per day"
            value={spendUnavailable ? '–' : spendSummary ? humanFriendlyCurrency(spendSummary.dailyAverageUsd) : null}
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
                                Last period averaged {humanFriendlyCurrency(spendSummary.previousDailyAverageUsd)} a day
                            </span>
                        )}
                </div>
            }
        >
            {spendSummary && (
                <span className="text-sm text-tertiary">
                    {spendSummary.productsWithSpend > 0
                        ? `Across ${pluralize(spendSummary.productsWithSpend, 'AI product')}`
                        : 'No AI spend this period yet'}
                </span>
            )}
        </AICreditsTile>
    )
}
