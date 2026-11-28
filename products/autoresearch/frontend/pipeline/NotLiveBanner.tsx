import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonCollapse } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { notLiveExplanation, trainingScheduleLogic } from '../trainingScheduleLogic'

/** Why the best model so far couldn't go live, when training tries again, and the raw reason on request. */
export function NotLiveBanner(): JSX.Element | null {
    const { pipeline, startTrainingResultLoading, firstRunCheckRunning } = useValues(autoresearchPipelineLogic)
    const { requestTraining } = useActions(autoresearchPipelineLogic)
    const { props } = useMountedLogic(autoresearchPipelineLogic)
    const { projectLimits, trainDisabledReason } = useValues(trainingScheduleLogic(props))
    const explanation = pipeline ? notLiveExplanation(pipeline, projectLimits) : null
    if (!pipeline || !explanation) {
        return null
    }
    return (
        <LemonBanner
            type="warning"
            action={{
                children: 'Run training now',
                onClick: () => requestTraining(),
                loading: startTrainingResultLoading || firstRunCheckRunning,
                disabledReason: trainDisabledReason,
                'data-attr': 'autoresearch-model-not-live-train',
            }}
        >
            <div className="font-semibold">The best model so far couldn't go live, so nothing is scored yet</div>
            <div>{explanation}</div>
            <LemonCollapse
                size="xsmall"
                embedded
                className="mt-1"
                panels={[
                    {
                        key: 'technical_details',
                        header: 'Technical details',
                        dataAttr: 'autoresearch-model-not-live-details',
                        content: <div className="text-xs font-mono break-words">{pipeline.not_promoted_reason}</div>,
                    },
                ]}
            />
        </LemonBanner>
    )
}
