import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AutoresearchTrainingRunApi } from '../generated/api.schemas'
import { ArtifactViewerModal } from './ArtifactViewerModal'
import { EmptyTab } from './EmptyTab'
import { TrainingRunRow } from './TrainingRunRow'

export function TrainingTab(): JSX.Element {
    const { pipeline, trainingRuns, trainingRunsLoading, trainingRunsError, startTrainingResultLoading } =
        useValues(autoresearchPipelineLogic)
    const { startTraining, loadTrainingRuns } = useActions(autoresearchPipelineLogic)
    const hasLiveRun = trainingRuns.some((run) => run.status === 'pending' || run.status === 'running')
    const trainDisabledReason = startTrainingResultLoading
        ? 'Starting…'
        : pipeline?.status === 'paused'
          ? 'Resume the model to train it'
          : hasLiveRun
            ? 'A training run is already in progress'
            : undefined

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <LemonButton
                    type="primary"
                    onClick={() => void startTraining()}
                    data-attr="autoresearch-model-train"
                    loading={startTrainingResultLoading}
                    disabledReason={trainDisabledReason}
                >
                    Run training
                </LemonButton>
            </div>
            {trainingRunsLoading ? (
                <Spinner />
            ) : trainingRunsError ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadTrainingRuns(),
                        'data-attr': 'autoresearch-model-training-runs-retry',
                    }}
                >
                    Couldn't load this model's training runs. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : trainingRuns.length === 0 ? (
                <EmptyTab icon={<IconRefresh />} title="No training runs yet">
                    Run training to kick off the autoresearch loop. The agent iterates on feature recipes, keeping only
                    the changes that improve holdout AUC.
                </EmptyTab>
            ) : (
                <div className="space-y-2">
                    {trainingRuns.map((run: AutoresearchTrainingRunApi) => (
                        <TrainingRunRow key={run.id} run={run} />
                    ))}
                </div>
            )}
            <ArtifactViewerModal />
        </div>
    )
}
