import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { SuggestionForm } from './SuggestionForm'
import { SuggestionList } from './SuggestionList'

/** A collapsed bar to suggest ideas for the next run, next to the button that starts one. */
export function SteerAgentBar(): JSX.Element {
    const { pipeline, startTrainingResultLoading, hasLiveTrainingRun, queuedSuggestionCount } =
        useValues(autoresearchPipelineLogic)
    const { startTraining, steerOpened } = useActions(autoresearchPipelineLogic)
    const trainDisabledReason = startTrainingResultLoading
        ? 'Starting…'
        : pipeline?.status === 'paused'
          ? 'Resume the model to train it'
          : hasLiveTrainingRun
            ? 'A training run is already in progress'
            : undefined
    return (
        <div className="flex flex-col @md:flex-row @md:items-start gap-2">
            <LemonCollapse
                className="flex-1 min-w-0 bg-surface-primary"
                onChange={(key) => key === 'steer' && steerOpened()}
                panels={[
                    {
                        key: 'steer',
                        dataAttr: 'autoresearch-steer-agent',
                        header: (
                            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
                                <span className="font-semibold">Steer the next run</span>
                                <span className="text-xs text-muted font-normal">
                                    Suggest an idea for the agent to try
                                </span>
                                {queuedSuggestionCount > 0 && (
                                    <LemonTag size="small">{`${queuedSuggestionCount} queued`}</LemonTag>
                                )}
                            </span>
                        ),
                        content: (
                            <div className="space-y-3">
                                <div className="text-xs text-muted">
                                    The agent reads queued suggestions at the start of each batch of experiments, then
                                    acts on or dismisses each one.
                                </div>
                                <SuggestionForm />
                                <SuggestionList />
                            </div>
                        ),
                    },
                ]}
            />
            <LemonButton
                type="primary"
                onClick={() => void startTraining()}
                data-attr="autoresearch-model-train"
                loading={startTrainingResultLoading}
                disabledReason={trainDisabledReason}
                className="self-start"
            >
                Run training
            </LemonButton>
        </div>
    )
}
