import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { cn } from 'lib/utils/css-classes'

import { EvaluationMetricTabs } from './EvaluationMetricTabs'
import { type BucketInterval, toChartValues } from './evaluationOverviewDisplay'
import { EvaluationOverviewMetricChart } from './EvaluationOverviewMetricChart'
import { EvaluationPassRateOverview } from './EvaluationPassRateOverview'
import { type OverviewMetric, type OverviewView, evaluationsOverviewLogic } from './evaluationsOverviewLogic'
import { EvaluationStatusGrid } from './EvaluationStatusGrid'

function viewTitle(view: OverviewView, metric: OverviewMetric, interval: BucketInterval): string {
    switch (view) {
        case 'over_time':
            return metric === 'pass_rate'
                ? 'Results over time'
                : metric === 'graded'
                  ? `Graded results each ${interval}`
                  : 'Negative sentiment over time'
        case 'by_bucket':
            return `Each evaluation, ${interval} by ${interval}`
    }
}

function viewSubtitle(view: OverviewView, interval: BucketInterval): string {
    switch (view) {
        case 'over_time':
            return 'Pick evaluations in the list to compare them.'
        case 'by_bucket':
            return `Every evaluation, most unusual ${interval}s first. Hover a${interval === 'hour' ? 'n' : ''} ${interval} for details.`
    }
}

function viewOptions(interval: BucketInterval): { value: OverviewView; label: string; 'data-attr': string }[] {
    return [
        { value: 'over_time', label: 'Over time', 'data-attr': 'evaluation-overview-view-over-time' },
        {
            value: 'by_bucket',
            label: interval === 'hour' ? 'Hour by hour' : 'Day by day',
            'data-attr': 'evaluation-overview-view-by-bucket',
        },
    ]
}

function ResultsBody(): JSX.Element {
    const { view, metric, overview, buckets, sentimentRow } = useValues(evaluationsOverviewLogic)

    if (view === 'by_bucket') {
        return <EvaluationStatusGrid />
    }
    if (metric === 'graded') {
        return (
            <EvaluationOverviewMetricChart
                label="Graded results"
                labels={buckets}
                values={overview?.totals.gradedTrend ?? []}
            />
        )
    }
    if (metric === 'sentiment' && sentimentRow) {
        return (
            <EvaluationOverviewMetricChart
                label="Negative share"
                labels={buckets}
                values={toChartValues(sentimentRow.trend.values)}
                color={getColorVar('danger')}
                percentage
            />
        )
    }
    return <EvaluationPassRateOverview />
}

/** One results card with a view picker, so the page shows a single chart at a time. */
export function EvaluationOverviewResults(): JSX.Element {
    const { view, metric, overview, overviewLoading, request, nothingGraded, exploreUrl, interval } =
        useValues(evaluationsOverviewLogic)
    const { setView, clickExplore } = useActions(evaluationsOverviewLogic)
    const loading = (overviewLoading || !request.ready) && !overview
    const showTabs = view === 'over_time' && !loading

    return (
        <div className="border rounded bg-surface-primary flex flex-col min-w-0">
            <div className={cn('flex flex-col gap-3 px-4 pt-3 border-b', !showTabs && 'pb-3')}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="flex flex-col min-w-0">
                        <h3 className="mb-0 text-base font-semibold">{viewTitle(view, metric, interval)}</h3>
                        {!loading && !nothingGraded && (view !== 'over_time' || metric === 'pass_rate') && (
                            <span className="text-xs text-secondary">{viewSubtitle(view, interval)}</span>
                        )}
                    </div>
                    {/* With nothing graded the picker only matters as the way back to the over time empty state. */}
                    {!loading && (!nothingGraded || view !== 'over_time') && (
                        <div className="flex flex-wrap items-center justify-end gap-2">
                            {/* Explore only works on the pass rate chart. It sits left of the view picker, so the picker
                            keeps its place when Explore comes and goes. */}
                            {exploreUrl && view === 'over_time' && metric === 'pass_rate' && (
                                <LemonButton
                                    size="small"
                                    icon={<IconGraph />}
                                    to={exploreUrl}
                                    onClick={clickExplore}
                                    tooltip="Open the pass rates as an insight, with one line per evaluation, to change filters or break them down"
                                    data-attr="evaluation-overview-explore"
                                >
                                    Explore
                                </LemonButton>
                            )}
                            <LemonSegmentedButton
                                size="small"
                                value={view}
                                onChange={setView}
                                options={viewOptions(interval)}
                            />
                        </div>
                    )}
                </div>
                {/* The day by day grid shows every evaluation the same way, so the metric tabs only steer the chart. */}
                {showTabs && <EvaluationMetricTabs />}
            </div>
            <div className="p-4">{loading ? <LemonSkeleton className="h-96 w-full" /> : <ResultsBody />}</div>
        </div>
    )
}
