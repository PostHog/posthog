import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { EvaluationDirectoryPicker } from './EvaluationDirectoryPicker'
import { RATE_LIMITED_MESSAGE } from './evaluationOverviewDisplay'
import { EvaluationOverviewResults } from './EvaluationOverviewResults'
import { EvaluationScopePicker } from './EvaluationScopePicker'
import { OVERVIEW_DATE_OPTIONS, evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationsOverview(): JSX.Element {
    const { dateFilter, request, overviewFailure, evaluationListFailed } = useValues(evaluationsOverviewLogic)
    const { setDates, retryOverview } = useActions(evaluationsOverviewLogic)

    return (
        <div className="@container flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <EvaluationDirectoryPicker />
                <EvaluationScopePicker />
                <DateFilter
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    onChange={setDates}
                    dateOptions={OVERVIEW_DATE_OPTIONS}
                    allowedRollingDateOptions={['hours', 'days', 'weeks', 'months']}
                />
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
