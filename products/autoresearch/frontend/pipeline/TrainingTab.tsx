import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AgentSearchChart } from './AgentSearchChart'
import { ArtifactViewerModal } from './ArtifactViewerModal'
import { EmptyTab } from './EmptyTab'
import { ExperimentLog } from './ExperimentLog'

export function TrainingTab(): JSX.Element {
    const { trainingRuns, trainingRunsLoading, trainingRunsError } = useValues(autoresearchPipelineLogic)
    const { loadTrainingRuns } = useActions(autoresearchPipelineLogic)

    return (
        <div className="space-y-4 min-w-0">
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
