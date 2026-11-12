import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { dominantDriver, modelQuality } from '../modelQuality'
import { ModelQualityTag } from '../ModelQualityTag'
import { PipelineStatusTag } from '../PipelineStatusTag'

/** The line under the model's question: status, quality verdict, and how many people the model scored. */
export function PipelineSummary(): JSX.Element | null {
    const { pipeline, champion } = useValues(autoresearchPipelineLogic)
    if (!pipeline) {
        return null
    }
    const quality = modelQuality({
        holdoutAuc: pipeline.champion_holdout_auc,
        realizedAuc: pipeline.champion_realized_auc,
        liftAt10: pipeline.champion_lift_at_10,
        isPreliminary: pipeline.champion_is_preliminary,
        target: pipeline.target_event,
    })
    const dominant = dominantDriver(champion?.model_explanation?.top_features)
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <PipelineStatusTag status={pipeline.status} />
            {quality && (
                <span className="flex items-center gap-1 min-w-0">
                    <ModelQualityTag
                        quality={quality}
                        holdoutAuc={pipeline.champion_holdout_auc}
                        realizedAuc={pipeline.champion_realized_auc}
                    />
                    <span className="text-secondary">{quality.sentence}</span>
                </span>
            )}
            {dominant && (
                <Tooltip
                    title={`${dominant} carries most of the prediction. See "What drives the live model" on the Accuracy tab.`}
                >
                    <LemonTag type="default">Mostly one signal</LemonTag>
                </Tooltip>
            )}
            <span className="text-secondary">
                {pipeline.people_scored != null
                    ? `${humanFriendlyNumber(pipeline.people_scored)} people scored`
                    : 'Not scored yet'}
                {pipeline.last_scored_at && ` · last scored ${dayjs(pipeline.last_scored_at).fromNow()}`}
            </span>
        </div>
    )
}
