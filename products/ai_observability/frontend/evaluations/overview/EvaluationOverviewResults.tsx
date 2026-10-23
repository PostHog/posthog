import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'

import { type BucketInterval, toChartValues } from './evaluationOverviewDisplay'
import { EvaluationOverviewMetricChart } from './EvaluationOverviewMetricChart'
import { EvaluationPassRateOverview } from './EvaluationPassRateOverview'
import { EvaluationRankedBars } from './EvaluationRankedBars'
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
        case 'ranked':
            return 'Each evaluation, ranked'
    }
}

function viewSubtitle(view: OverviewView, interval: BucketInterval): string {
    switch (view) {
        case 'over_time':
            return 'Pick evaluations in the list to compare them.'
        case 'by_bucket':
            return `Every evaluation, most unusual ${interval}s first. Hover a${interval === 'hour' ? 'n' : ''} ${interval} for details.`
        case 'ranked':
            return 'Lowest first, on a scale where higher is better. Click a row to open it.'
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
        { value: 'ranked', label: 'Ranked', 'data-attr': 'evaluation-overview-view-ranked' },
    ]
}

function ResultsBody(): JSX.Element {
    const { view, metric, overview, buckets, sentimentRow, ranked } = useValues(evaluationsOverviewLogic)

    if (view === 'by_bucket') {
        return <EvaluationStatusGrid />
    }
    if (view === 'ranked') {
        return (
            <div className="flex flex-col gap-6">
                {ranked.results.length > 0 && (
                    <EvaluationRankedBars labelHeader="Evaluation" valueHeader="Result" items={ranked.results} />
                )}
                {ranked.labels.length > 0 && (
                    <EvaluationRankedBars
                        labelHeader="Labels"
                        valueHeader="Tracked label"
                        fullScale
                        items={ranked.labels}
                    />
                )}
            </div>
        )
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

    return (
        <div className="border rounded bg-surface-primary flex flex-col min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b">
                <div className="flex flex-col min-w-0">
                    <h3 className="mb-0 text-base font-semibold">{viewTitle(view, metric, interval)}</h3>
                    {!loading && !nothingGraded && (view !== 'over_time' || metric === 'pass_rate') && (
                        <span className="text-xs text-secondary">{viewSubtitle(view, interval)}</span>
                    )}
                </div>
                {!loading && !nothingGraded && (
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
            <div className="p-4">{loading ? <LemonSkeleton className="h-96 w-full" /> : <ResultsBody />}</div>
        </div>
    )
}
