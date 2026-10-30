import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import {
    ACCURACY_CUTOFFS,
    ACCURACY_TREND_METRICS,
    AccuracyTrendMetric,
    accuracyTrendSummary,
    trendMetricUsesCutoff,
} from '../onlinePerformance'
import { eventName } from '../pipelineQuestion'
import { AccuracyTrendChart } from './AccuracyTrendChart'
import { AccuracyTrendDatePanel } from './AccuracyTrendDatePanel'
import { SectionCard } from './SectionCard'

function description(metric: AccuracyTrendMetric, target: string): string {
    switch (metric) {
        case 'ranking':
            return `How well the model ranked people who did ${target} above people who did not, on each checked date. 0.5 is a coin flip and 1 is a perfect ranking. The dashed line is the holdout AUC the model got in training.`
        case 'hit_rate':
            return `The share of flagged people who did ${target}, on each checked date.`
        case 'coverage':
            return `The share of everyone who did ${target} that the model flagged, on each checked date.`
        case 'lift':
            return `How many times more often flagged people did ${target} than everyone scored, on each checked date.`
        case 'calibration':
            return `The average score the model gave against the share of people who really did ${target}. When the lines stay close, you can read the scores as probabilities.`
    }
}

/** The picked online metric per prediction date, for the champion and optionally its challengers. */
export function AccuracyTrendCard(): JSX.Element {
    const {
        pipeline,
        champion,
        onlinePerformance,
        accuracyTrend,
        accuracyTrendMetric: metric,
        accuracyCutoff,
        showChallengersInTrend,
        hasChallengerPerformance,
        hoveredAccuracyDate,
    } = useValues(autoresearchPipelineLogic)
    const { setAccuracyTrendMetric, setAccuracyCutoff, setShowChallengersInTrend, setHoveredAccuracyDate } =
        useActions(autoresearchPipelineLogic)
    const targetEvent = pipeline?.target_event ?? ''
    const holdoutAuc = champion?.holdout_score ?? null
    const { dates } = accuracyTrend
    const panelDate =
        hoveredAccuracyDate && dates.includes(hoveredAccuracyDate) ? hoveredAccuracyDate : dates[dates.length - 1]
    const summary = accuracyTrendSummary(onlinePerformance, metric, accuracyCutoff, targetEvent, holdoutAuc)

    return (
        <SectionCard
            title="Accuracy over time"
            description={description(metric, eventName(targetEvent))}
            actions={
                <LemonSwitch
                    label="Compare challengers"
                    checked={showChallengersInTrend}
                    onChange={setShowChallengersInTrend}
                    disabledReason={
                        !hasChallengerPerformance ? 'No challenger has been checked against real outcomes yet.' : null
                    }
                    bordered
                    size="small"
                    data-attr="autoresearch-model-accuracy-trend-challengers"
                />
            }
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonSegmentedButton
                    size="small"
                    value={metric}
                    onChange={setAccuracyTrendMetric}
                    options={ACCURACY_TREND_METRICS.map(({ key, label }) => ({
                        value: key,
                        label,
                        'data-attr': `autoresearch-model-accuracy-trend-metric-${key}`,
                    }))}
                />
                {trendMetricUsesCutoff(metric) && (
                    <LemonSegmentedButton
                        size="small"
                        value={accuracyCutoff}
                        onChange={(cutoff) => setAccuracyCutoff(cutoff, 'trend')}
                        options={ACCURACY_CUTOFFS.map(({ key, label }) => ({
                            value: key,
                            label,
                            'data-attr': `autoresearch-model-accuracy-trend-cutoff-${key}`,
                        }))}
                    />
                )}
            </div>
            {accuracyTrend.series[0].points.length === 0 || !panelDate ? (
                <p className="text-sm text-muted mb-0">
                    {metric === 'ranking'
                        ? `No checked date had both people who did ${eventName(targetEvent)} and people who did not, so there is no ranking score yet.`
                        : 'This metric starts from the next checked date. Dates checked before it existed have no value.'}
                </p>
            ) : (
                <div className="@container">
                    <div className="flex flex-col @3xl:flex-row gap-4">
                        <div className="flex-1 min-w-0">
                            <AccuracyTrendChart
                                trend={accuracyTrend}
                                metric={metric}
                                holdoutAuc={holdoutAuc}
                                hoveredDate={hoveredAccuracyDate}
                                onHover={setHoveredAccuracyDate}
                            />
                        </div>
                        <AccuracyTrendDatePanel trend={accuracyTrend} metric={metric} date={panelDate} />
                    </div>
                </div>
            )}
            {summary && <p className="text-sm mb-0">{summary}</p>}
        </SectionCard>
    )
}
