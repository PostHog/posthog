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
import { modelCardState } from './modelCardState'
import { modelQuality } from './modelQuality'
import { ModelQualityTag } from './ModelQualityTag'
import { MetricSparkline } from './pipeline/MetricSparkline'
import { pipelineQuestion } from './pipelineQuestion'
import { PipelineStatusTag } from './PipelineStatusTag'

function ScoredBody({ pipeline }: { pipeline: AutoresearchPipelineApi }): JSX.Element {
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
    const trend = pipeline.champion_realized_auc_trend.map((point) => ({
        date: point.prediction_date,
        value: point.realized_auc,
    }))
    return (
        <div className="flex items-center justify-between gap-2">
            <div className="flex flex-col gap-1 min-w-0">
                <div className="flex items-center gap-1">
                    <ModelQualityTag
                        quality={quality}
                        holdoutAuc={pipeline.champion_holdout_auc}
                        realizedAuc={pipeline.champion_realized_auc}
                    />
                    <span className="text-xs text-secondary">{quality.basis}</span>
                </div>
                <span className="text-xs text-secondary break-words">{quality.sentence}</span>
            </div>
            {trend.length > 1 && (
                <Tooltip title="Realized AUC on recent checked dates">
                    <span className="shrink-0">
                        <MetricSparkline points={trend} width={96} height={32} />
                    </span>
                </Tooltip>
            )}
        </div>
    )
}

function TrainingBody({ liveRun }: { liveRun: AutoresearchLiveTrainingRunApi | null }): JSX.Element {
    if (!liveRun) {
        return <span className="text-secondary">Starting the first training run…</span>
    }
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2 text-xs">
                <span className="font-semibold">
                    {`Experiment ${liveRun.experiment_count} of ${liveRun.iteration_budget}`}
                </span>
                {liveRun.best_holdout_score != null && (
                    <span className="text-secondary">{`Best AUC so far ${liveRun.best_holdout_score.toFixed(2)}`}</span>
                )}
            </div>
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
            <div className="rounded border bg-surface-secondary p-3">
                {state === 'training' ? (
                    <TrainingBody liveRun={pipeline.live_training_run} />
                ) : state === 'draft' ? (
                    <DraftBody pipeline={pipeline} />
                ) : (
                    <ScoredBody pipeline={pipeline} />
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
