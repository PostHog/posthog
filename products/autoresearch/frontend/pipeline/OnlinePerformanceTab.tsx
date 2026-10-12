import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonBanner, LemonCollapse, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { accuracyHeadline, percent, precisionRecallSentence, rankingSentence } from '../onlinePerformance'
import { ConfusionMatrixCard } from './ConfusionMatrixCard'
import { EmptyTab } from './EmptyTab'
import { RealizedAucChart } from './RealizedAucChart'
import { ScoreNowButton } from './ScoreNowButton'
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
        champion,
        onlinePerformance,
        onlinePerformanceLoading,
        onlinePerformanceError,
        latestChampionPerformance,
        realizedAucPoints,
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
        return <NotCheckedYet />
    }

    const ranking = rankingSentence(latestChampionPerformance, pipeline.target_event)
    const precisionRecall = championConfusion
        ? precisionRecallSentence(championConfusion, accuracyCutoff, pipeline.target_event)
        : null
    const latestDate = dayjs(latestChampionPerformance.prediction_date).format('MMM D')

    return (
        <div className="space-y-6">
            <div className="space-y-1">
                <p className="text-base font-semibold mb-0">
                    {accuracyHeadline(latestChampionPerformance, pipeline.target_event)}
                </p>
                {ranking && <p className="text-sm text-muted mb-0">{ranking}</p>}
                {precisionRecall && <p className="text-sm text-muted mb-0">{precisionRecall}</p>}
            </div>

            <ConfusionMatrixCard />

            {segmentCalibration.length > 0 && (
                <section className="space-y-2">
                    <h3 className="text-sm font-semibold mb-0">Predicted and actual rate by segment, {latestDate}</h3>
                    <SegmentCalibrationBars segments={segmentCalibration} />
                </section>
            )}

            {realizedAucPoints.length > 0 && (
                <section className="space-y-2">
                    <h3 className="text-sm font-semibold mb-0">Realized AUC over time</h3>
                    <p className="text-xs text-muted mb-0">
                        Realized AUC measures how well the model ranked people who did {pipeline.target_event} above
                        people who did not. 0.5 is a coin flip and 1 is a perfect ranking. The holdout line is the score
                        the model got in training.
                    </p>
                    <RealizedAucChart points={realizedAucPoints} holdoutAuc={champion?.holdout_score ?? null} />
                </section>
            )}

            <LemonCollapse
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
                                    many conversions as random. Precision at 10%: share of the top 10% who did{' '}
                                    {pipeline.target_event}. Recall at 10%: share of everyone who did it that the top
                                    10% includes. Average precision: precision averaged over every cutoff, higher is
                                    better.
                                </p>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
