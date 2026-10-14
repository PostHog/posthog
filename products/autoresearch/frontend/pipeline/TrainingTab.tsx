import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AgentSearchChart } from './AgentSearchChart'
import { ArtifactViewerModal } from './ArtifactViewerModal'
import { EmptyTab } from './EmptyTab'
import { ExperimentLog } from './ExperimentLog'

export function TrainingTab(): JSX.Element {
    const {
        pipeline,
        trainingRuns,
        trainingRunsLoading,
        trainingRunsError,
        startTrainingResultLoading,
        hasLiveTrainingRun,
    } = useValues(autoresearchPipelineLogic)
    const { startTraining, loadTrainingRuns } = useActions(autoresearchPipelineLogic)
    const trainDisabledReason = startTrainingResultLoading
        ? 'Starting…'
        : pipeline?.status === 'paused'
          ? 'Resume the model to train it'
          : hasLiveTrainingRun
            ? 'A training run is already in progress'
            : undefined

    return (
        <div className="space-y-4 min-w-0">
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
            {/* Polling reloads the runs while one is live, so keep the loaded runs on screen during a reload. */}
            {trainingRuns.length === 0 && trainingRunsLoading ? (
                <Spinner />
            ) : trainingRuns.length === 0 && trainingRunsError ? (
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
                <>
                    <AgentSearchChart />
                    <ExperimentLog />
                </>
            )}
            <ArtifactViewerModal />
        </div>
    )
}
