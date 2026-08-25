import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AutoresearchTrainingRunApi } from '../generated/api.schemas'
import { ArtifactViewerModal } from './ArtifactViewerModal'
import { EmptyTab } from './EmptyTab'
import { TrainingRunRow } from './TrainingRunRow'

export function TrainingTab(): JSX.Element {
    const { trainingRuns, trainingRunsLoading, startTrainingResultLoading } = useValues(autoresearchPipelineLogic)
    const { startTraining } = useActions(autoresearchPipelineLogic)

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <LemonButton
                    type="primary"
                    onClick={() => void startTraining()}
                    loading={startTrainingResultLoading}
                    disabledReason={startTrainingResultLoading ? 'Starting…' : undefined}
                >
                    Run training
                </LemonButton>
            </div>
            {trainingRunsLoading ? (
                <Spinner />
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
