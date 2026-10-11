import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { autoresearchLogic } from './autoresearchLogic'
import { AutoresearchLiveTrainingRunApi, AutoresearchPipelineApi } from './generated/api.schemas'
import { ModelCardMenu } from './ModelCardMenu'
import { firstCheckCountdown, modelCardState } from './modelCardState'
import { modelQuality } from './modelQuality'
import { ModelQualityTag } from './ModelQualityTag'
import { MetricSparkline } from './pipeline/MetricSparkline'
import { pipelineQuestion } from './pipelineQuestion'
import { PipelineStatusTag } from './PipelineStatusTag'
import { formatProbability } from './predictionSegments'

const TEST_DATA_COLOR = 'var(--color-text-secondary)'
const REAL_OUTCOME_COLOR = 'var(--success)'

function Headline({ value, label }: { value: string; label: string }): JSX.Element {
    return (
        <div className="flex flex-col min-w-0">
            <span className="text-xl font-semibold leading-tight">{value}</span>
            <span className="text-xs text-secondary break-words">{label}</span>
        </div>
    )
}

function TrendChart({
    points,
    color,
    title,
}: {
    points: { date: string; value: number }[]
    color: string
    title: string
}): JSX.Element | null {
    if (points.length < 2) {
        return null
    }
    return (
        <Tooltip title={title}>
            <span className="shrink-0">
                <MetricSparkline points={points} color={color} width={96} height={32} />
            </span>
        </Tooltip>
    )
}

/** Until enough predictions are checked, Likely uses the fixed cut point, so the tooltip says so. */
function likelyTooltip(threshold: number, confirmed: boolean): string {
    return confirmed
        ? `Likely means a score of ${formatProbability(threshold)} or more when the model last scored.`
        : `Likely means a score of ${formatProbability(threshold)} or more until enough predictions are checked.`
}

function AwaitingCheckBody({ pipeline }: { pipeline: AutoresearchPipelineApi }): JSX.Element {
    const quality = modelQuality({
        holdoutAuc: pipeline.champion_holdout_auc,
        realizedAuc: pipeline.champion_realized_auc,
        liftAt10: pipeline.champion_lift_at_10,
        isPreliminary: pipeline.champion_is_preliminary,
        target: pipeline.target_event,
    })
    if (!quality) {
        return <span className="text-secondary">No quality measured yet</span>
    }
    const countdown =
        pipeline.first_check_expected_at && pipeline.horizon_days
            ? firstCheckCountdown(pipeline.first_check_expected_at, pipeline.horizon_days)
            : null
    const trend = pipeline.champion_training_trend.map((point) => ({
        date: String(point.iteration_number),
        value: point.best_holdout_score,
    }))
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                {pipeline.likely_count != null && pipeline.likely_threshold != null ? (
                    <Tooltip title={likelyTooltip(pipeline.likely_threshold, false)}>
                        <span className="min-w-0">
                            <Headline
                                value={humanFriendlyNumber(pipeline.likely_count)}
                                label={
                                    pipeline.horizon_days
                                        ? `people likely to do ${pipeline.target_event} in the next ${pluralize(pipeline.horizon_days, 'day')}`
                                        : `people likely to do ${pipeline.target_event}`
                                }
                            />
                        </span>
                    </Tooltip>
                ) : (
                    <span className="text-xs text-secondary break-words">{quality.sentence}</span>
                )}
                <TrendChart
                    points={trend}
                    color={TEST_DATA_COLOR}
                    title="Best test AUC per experiment of the run that trained this model"
                />
            </div>
            <div className="flex items-center gap-1">
                <ModelQualityTag
                    quality={quality}
                    holdoutAuc={pipeline.champion_holdout_auc}
                    realizedAuc={pipeline.champion_realized_auc}
                />
                <span className="text-xs text-secondary">{`on test data · AUC ${quality.auc.toFixed(2)}`}</span>
            </div>
            {countdown && (
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-secondary">{countdown.label}</span>
                    <LemonProgress percent={countdown.percent} strokeColor={TEST_DATA_COLOR} />
                </div>
            )}
        </div>
    )
}

function ConfirmedBody({ pipeline }: { pipeline: AutoresearchPipelineApi }): JSX.Element | null {
    const quality = modelQuality({
        holdoutAuc: pipeline.champion_holdout_auc,
        realizedAuc: pipeline.champion_realized_auc,
        liftAt10: pipeline.champion_lift_at_10,
        isPreliminary: pipeline.champion_is_preliminary,
        target: pipeline.target_event,
    })
    if (!quality) {
        return null
    }
    const trend = pipeline.champion_realized_auc_trend.map((point) => ({
        date: point.prediction_date,
        value: point.realized_auc,
    }))
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                {pipeline.champion_lift_at_10 != null ? (
                    <Headline value={`${pipeline.champion_lift_at_10.toFixed(1)}× lift`} label={quality.sentence} />
                ) : (
                    <span className="text-xs text-secondary break-words">{quality.sentence}</span>
                )}
                <TrendChart points={trend} color={REAL_OUTCOME_COLOR} title="Realized AUC on recent checked dates" />
            </div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="flex items-center gap-1">
                    <ModelQualityTag
                        quality={quality}
                        holdoutAuc={pipeline.champion_holdout_auc}
                        realizedAuc={pipeline.champion_realized_auc}
                    />
                    <span className="text-xs text-secondary">{`confirmed · real AUC ${quality.auc.toFixed(2)}`}</span>
                </span>
                {pipeline.likely_count != null && pipeline.likely_threshold != null && (
                    <Tooltip title={likelyTooltip(pipeline.likely_threshold, true)}>
                        <span className="text-xs text-secondary">
                            {`${humanFriendlyNumber(pipeline.likely_count)} people likely`}
                        </span>
                    </Tooltip>
                )}
            </div>
        </div>
    )
}

function RetrainingStrip({
    liveRun,
    liveAuc,
}: {
    liveRun: AutoresearchLiveTrainingRunApi
    liveAuc: number | null
}): JSX.Element {
    const details = [
        `experiment ${liveRun.experiment_count} of ${liveRun.iteration_budget}`,
        liveRun.best_holdout_score != null
            ? `best test AUC ${liveRun.best_holdout_score.toFixed(2)}${liveAuc != null ? ` vs live ${liveAuc.toFixed(2)}` : ''}`
            : null,
    ]
    return (
        <div className="rounded border px-2 py-1 text-xs text-secondary">
            <span className="font-semibold text-primary">Retraining</span>
            {details
                .filter(Boolean)
                .map((detail) => ` · ${detail}`)
                .join('')}
        </div>
    )
}

function TrainingBody({ liveRun }: { liveRun: AutoresearchLiveTrainingRunApi | null }): JSX.Element {
    if (!liveRun) {
        return <span className="text-secondary">Starting the first training run…</span>
    }
    return (
        <div className="flex flex-col gap-1">
            <Headline
                value={liveRun.best_holdout_score != null ? liveRun.best_holdout_score.toFixed(2) : 'No score yet'}
                label={`Best test AUC so far · experiment ${liveRun.experiment_count} of ${liveRun.iteration_budget}`}
            />
            <LemonProgress percent={(liveRun.experiment_count / liveRun.iteration_budget) * 100} />
            {liveRun.latest_agent_description && (
                <span className="text-xs text-secondary truncate" title={liveRun.latest_agent_description}>
                    {liveRun.latest_agent_description}
                </span>
            )}
        </div>
    )
}

function DraftBody({ pipeline }: { pipeline: AutoresearchPipelineApi }): JSX.Element {
    const { mutatingPipelineIds } = useValues(autoresearchLogic)
    const { startTraining } = useActions(autoresearchLogic)
    const mutating = !!mutatingPipelineIds[pipeline.id]
    return (
        <div className="flex items-center justify-between gap-2">
            <span className="text-secondary">Not trained yet</span>
            <LemonButton
                type="primary"
                size="small"
                loading={mutating}
                disabledReason={mutating ? 'Another change is still saving' : undefined}
                onClick={() => startTraining(pipeline)}
                data-attr="autoresearch-model-card-train"
            >
                Start training
            </LemonButton>
        </div>
    )
}

export function AutoresearchModelCard({ pipeline }: { pipeline: AutoresearchPipelineApi }): JSX.Element {
    const { modelCardOpened } = useActions(autoresearchLogic)
    const state = modelCardState(pipeline)
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4 min-w-0">
            <div className="flex items-center justify-between gap-2">
                <PipelineStatusTag status={pipeline.status} />
                <div className="flex items-center gap-1">
                    {pipeline.cadence_days != null && (
                        <span className="text-xs text-secondary">
                            {pipeline.cadence_days === 1
                                ? 'Scores daily'
                                : `Scores every ${pipeline.cadence_days} days`}
                        </span>
                    )}
                    <ModelCardMenu pipeline={pipeline} />
                </div>
            </div>
            <div className="flex flex-col gap-0.5 min-w-0">
                <Link
                    to={urls.autoresearchPipeline(pipeline.id)}
                    onClick={() => modelCardOpened(pipeline.id)}
                    className="font-semibold text-base break-words"
                    data-attr="autoresearch-model-card"
                >
                    {pipelineQuestion(pipeline)}
                </Link>
                <span className="text-xs text-secondary truncate">
                    {pipeline.name} · {pipeline.target_event}
                </span>
            </div>
            <div className="flex flex-col gap-1">
                <div className="rounded border bg-surface-secondary p-3">
                    {state === 'training' ? (
                        <TrainingBody liveRun={pipeline.live_training_run} />
                    ) : state === 'draft' ? (
                        <DraftBody pipeline={pipeline} />
                    ) : state === 'awaiting_check' ? (
                        <AwaitingCheckBody pipeline={pipeline} />
                    ) : (
                        <ConfirmedBody pipeline={pipeline} />
                    )}
                </div>
                {state !== 'training' && pipeline.live_training_run && (
                    <RetrainingStrip liveRun={pipeline.live_training_run} liveAuc={pipeline.champion_holdout_auc} />
                )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-secondary mt-auto">
                <span>
                    {[
                        pipeline.people_scored != null
                            ? `${humanFriendlyNumber(pipeline.people_scored)} people scored`
                            : 'Not scored yet',
                        pipeline.last_scored_at ? dayjs(pipeline.last_scored_at).fromNow() : null,
                    ]
                        .filter(Boolean)
                        .join(' · ')}
                </span>
                <span>{`${pluralize(pipeline.training_run_count, 'run')} · ${pluralize(pipeline.experiment_count, 'experiment')}`}</span>
            </div>
        </LemonCard>
    )
}
