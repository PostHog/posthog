import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonBanner, LemonCollapse, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { accuracyStats, accuracySummary, percent } from '../onlinePerformance'
import { eventName } from '../pipelineQuestion'
import { AccuracyTrendCard } from './AccuracyTrendCard'
import { ConfusionMatrixCard } from './ConfusionMatrixCard'
import { EmptyTab } from './EmptyTab'
import { LiveModelDrivers } from './LiveModelDrivers'
import { MetricCard } from './MetricCard'
import { ScoreNowButton } from './ScoreNowButton'
import { SectionCard } from './SectionCard'
import { SegmentCalibrationBars } from './SegmentCalibrationBars'

const MODEL_ROLE: Record<string, { type: 'success' | 'default' | 'highlight'; label: string }> = {
    champion: { type: 'success', label: 'Champion' },
    challenger: { type: 'highlight', label: 'Challenger' },
    archived: { type: 'default', label: 'Archived' },
}

function fmt(value: number | null, decimals = 3): string {
    return value != null ? value.toFixed(decimals) : '—'
}

function fmtPercent(value: number | null | undefined): string {
    return value != null ? percent(value) : '—'
}

function NotCheckedYet(): JSX.Element {
    const { pipeline, firstCheck } = useValues(autoresearchPipelineLogic)
    const horizon = pluralize(pipeline?.horizon_days ?? 0, 'day')
    return (
        <EmptyTab icon={<IconGraph />} title="Not checked against real outcomes yet" cta={<ScoreNowButton />}>
            PostHog checks each prediction against what people really did, {horizon} after the prediction.{' '}
            {!firstCheck
                ? `Score the model to start. The first check comes ${horizon} after the first scoring run.`
                : firstCheck.isAfter(dayjs())
                  ? `The first check is due on ${firstCheck.format('MMM D, YYYY')}.`
                  : `The first scored date matured on ${firstCheck.format('MMM D, YYYY')}. The first check runs on the next daily schedule.`}
        </EmptyTab>
    )
}

export function OnlinePerformanceTab(): JSX.Element {
    const {
        pipeline,
        onlinePerformance,
        onlinePerformanceLoading,
        onlinePerformanceError,
        latestChampionPerformance,
        segmentCalibration,
        accuracyCutoff,
        championConfusion,
    } = useValues(autoresearchPipelineLogic)
    const { loadOnlinePerformance } = useActions(autoresearchPipelineLogic)

    if (onlinePerformanceLoading && onlinePerformance.length === 0) {
        return <Spinner />
    }

    if (onlinePerformanceError) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Retry',
                    onClick: () => loadOnlinePerformance(),
                    'data-attr': 'autoresearch-model-accuracy-retry',
                }}
            >
                Couldn't load this model's accuracy. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }

    if (!latestChampionPerformance || !pipeline) {
        return (
            <div className="space-y-6">
                <NotCheckedYet />
                <LiveModelDrivers />
            </div>
        )
    }

    const target = eventName(pipeline.target_event)
    const summary = championConfusion ? accuracySummary(championConfusion, accuracyCutoff, pipeline.target_event) : null
    const latestDate = dayjs(latestChampionPerformance.prediction_date).format('MMM D')

    return (
        <div className="space-y-6">
            <SectionCard>
                <div className="@container">
                    <div className="grid grid-cols-1 @sm:grid-cols-2 @3xl:grid-cols-4 gap-2">
                        {accuracyStats(latestChampionPerformance, pipeline.target_event).map(({ key, ...stat }) => (
                            <MetricCard key={key} {...stat} />
                        ))}
                    </div>
                </div>
                {summary && <p className="text-sm mb-0">{summary}</p>}
            </SectionCard>

            <ConfusionMatrixCard />

            {segmentCalibration.length > 0 && (
                <SectionCard title={`Predicted and actual rate by segment, ${latestDate}`}>
                    <SegmentCalibrationBars segments={segmentCalibration} />
                </SectionCard>
            )}

            <AccuracyTrendCard />

            <LiveModelDrivers />

            <LemonCollapse
                className="bg-surface-primary"
                panels={[
                    {
                        key: 'history',
                        header: `All checked dates (${onlinePerformance.length})`,
                        content: (
                            <div className="space-y-2">
                                <LemonTable
                                    dataSource={onlinePerformance}
                                    rowKey={(row) => `${row.validation_run_id}-${row.model_id}`}
                                    columns={[
                                        {
                                            title: 'Prediction date',
                                            render: (_, row) => (
                                                <span className="font-mono">{row.prediction_date}</span>
                                            ),
                                        },
                                        {
                                            title: 'Model',
                                            tooltip: 'The role the model held when it made these predictions.',
                                            render: (_, row) => (
                                                <LemonTag type={MODEL_ROLE[row.emitted_role]?.type ?? 'default'}>
                                                    {MODEL_ROLE[row.emitted_role]?.label ?? row.emitted_role}
                                                </LemonTag>
                                            ),
                                        },
                                        { title: 'Users scored', render: (_, row) => row.n_scored.toLocaleString() },
                                        {
                                            title: 'Realized AUC',
                                            render: (_, row) => (
                                                <span className="font-semibold">{fmt(row.realized_auc)}</span>
                                            ),
                                        },
                                        { title: 'Brier score', render: (_, row) => fmt(row.brier_score) },
                                        { title: 'Calibration error', render: (_, row) => fmt(row.calibration_error) },
                                        { title: 'Lift at 10%', render: (_, row) => `${fmt(row.lift_at_10, 2)}×` },
                                        { title: 'Lift at 20%', render: (_, row) => `${fmt(row.lift_at_20, 2)}×` },
                                        {
                                            title: 'Precision at 10%',
                                            render: (_, row) => fmtPercent(row.confusion?.top_10.precision),
                                        },
                                        {
                                            title: 'Recall at 10%',
                                            render: (_, row) => fmtPercent(row.confusion?.top_10.recall),
                                        },
                                        { title: 'Average precision', render: (_, row) => fmt(row.average_precision) },
                                    ]}
                                />
                                <p className="text-xs text-muted mb-0">
                                    Realized AUC: higher is better. Brier score and calibration error (ECE): lower is
                                    better. ECE measures how far predicted probabilities drift from observed rates. Lift
                                    at k%: ratio of positives in the top k% vs a random sample, so 2× means twice as
                                    many conversions as random. Precision at 10%: share of the top 10% who did {target}.
                                    Recall at 10%: share of everyone who did it that the top 10% includes. Average
                                    precision: precision averaged over every cutoff, higher is better.
                                </p>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
