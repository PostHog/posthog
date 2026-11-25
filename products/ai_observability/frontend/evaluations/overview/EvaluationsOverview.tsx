import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { RATE_LIMITED_MESSAGE } from './evaluationOverviewDisplay'
import { EvaluationOverviewResults } from './EvaluationOverviewResults'
import { EvaluationQuickFilters } from './EvaluationQuickFilters'
import { OVERVIEW_DATE_OPTIONS, evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationsOverview(): JSX.Element {
    const { dateFilter, request, overviewFailure, evaluationListFailed } = useValues(evaluationsOverviewLogic)
    const { setDates, retryOverview } = useActions(evaluationsOverviewLogic)

    return (
        <div className="@container flex flex-col gap-4">
            {/* Every filter here scopes the chart, its stats and the evaluations table below. */}
            <div className="flex flex-wrap items-center gap-2">
                <DateFilter
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    onChange={setDates}
                    dateOptions={OVERVIEW_DATE_OPTIONS}
                    allowedRollingDateOptions={['hours', 'days', 'weeks', 'months']}
                />
                <EvaluationQuickFilters />
            </div>
            {request.notice ? (
                <LemonBanner type="info">{request.notice}</LemonBanner>
            ) : overviewFailure ? (
                <LemonBanner
                    type={overviewFailure === 'rate_limited' ? 'warning' : 'error'}
                    action={{
                        children: 'Try again',
                        onClick: () => retryOverview(),
                        'data-attr': 'evaluation-overview-retry',
                    }}
                >
                    {overviewFailure === 'rate_limited' ? RATE_LIMITED_MESSAGE : "Couldn't load evaluation results."}
                </LemonBanner>
            ) : (
                <>
                    {evaluationListFailed && (
                        <LemonBanner
                            type="warning"
                            action={{
                                children: 'Try again',
                                onClick: () => retryOverview(),
                                'data-attr': 'evaluation-overview-list-retry',
                            }}
                        >
                            Couldn't load the evaluation list, so editing evaluations and picking them is unavailable.
                        </LemonBanner>
                    )}
                    <EvaluationOverviewResults />
                </>
            )}
        </div>
    )
}
