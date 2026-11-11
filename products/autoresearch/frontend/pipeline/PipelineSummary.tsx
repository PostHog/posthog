import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { modelQuality } from '../modelQuality'
import { ModelQualityTag } from '../ModelQualityTag'
import { PipelineStatusTag } from '../PipelineStatusTag'

/** The line under the model's question: status, quality verdict, and how many people the model scored. */
export function PipelineSummary(): JSX.Element | null {
    const { pipeline } = useValues(autoresearchPipelineLogic)
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
            <span className="text-secondary">
                {pipeline.people_scored != null
                    ? `${humanFriendlyNumber(pipeline.people_scored)} people scored`
                    : 'Not scored yet'}
                {pipeline.last_scored_at && ` · last scored ${dayjs(pipeline.last_scored_at).fromNow()}`}
            </span>
        </div>
    )
}
