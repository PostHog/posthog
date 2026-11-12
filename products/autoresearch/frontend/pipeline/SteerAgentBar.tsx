import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { trainingScheduleLogic } from '../trainingScheduleLogic'
import { SuggestionForm } from './SuggestionForm'
import { SuggestionList } from './SuggestionList'

/** A collapsed bar to suggest ideas for the next run, next to the button that starts one. */
export function SteerAgentBar(): JSX.Element {
    const { pipeline, startTrainingResultLoading, hasLiveTrainingRun, queuedSuggestionCount, stoppingTraining } =
        useValues(autoresearchPipelineLogic)
    const { startTraining, steerOpened, stopTraining } = useActions(autoresearchPipelineLogic)
    const { props } = useMountedLogic(autoresearchPipelineLogic)
    const { trainDisabledByLimitReason } = useValues(trainingScheduleLogic(props))
    const trainDisabledReason = startTrainingResultLoading
        ? 'Starting…'
        : pipeline?.status === 'paused'
          ? 'Resume the model to train it'
          : trainDisabledByLimitReason
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
            {hasLiveTrainingRun ? (
                <LemonButton
                    type="secondary"
                    status="danger"
                    onClick={() =>
                        LemonDialog.open({
                            title: 'Stop this training run?',
                            description:
                                pipeline?.status === 'bootstrapping'
                                    ? 'The agent stops now and no model comes from this run. The model goes back to draft, so you can change its setup before you train it again. The run still counts toward your daily training limit.'
                                    : 'The agent stops now and no model comes from this run. The current model keeps scoring. The run still counts toward your daily training limit.',
                            primaryButton: {
                                children: 'Stop training',
                                status: 'danger',
                                onClick: () => stopTraining(),
                            },
                            secondaryButton: { children: 'Keep training' },
                        })
                    }
                    data-attr="autoresearch-model-stop-training"
                    loading={stoppingTraining}
                    className="self-start"
                >
                    Stop training
                </LemonButton>
            ) : (
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
            )}
        </div>
    )
}
