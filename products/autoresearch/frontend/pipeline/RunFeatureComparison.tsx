import { useActions, useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic, featureChanges } from '../autoresearchPipelineLogic'
import { AutoresearchModelApi, AutoresearchModelRoleEnumApi } from '../generated/api.schemas'
import { FeatureImportanceChart } from './FeatureImportanceChart'

const ROLE_LABEL: Record<AutoresearchModelRoleEnumApi, string> = {
    champion: 'Champion',
    challenger: 'Challenger',
    archived: 'Archived',
}

function holdoutLabel(model: AutoresearchModelApi): string {
    return model.holdout_score != null ? `holdout AUC ${model.holdout_score.toFixed(3)}` : 'no holdout AUC'
}

/** The feature importances of the model a training run produced, next to the current champion's. */
export function RunFeatureComparison({ runId }: { runId: string }): JSX.Element {
    const { modelByTrainingRun, champion, modelsLoading, modelsError } = useValues(autoresearchPipelineLogic)
    const { loadModels } = useActions(autoresearchPipelineLogic)
    const model = modelByTrainingRun[runId]
    if (!model) {
        return modelsLoading ? (
            <Spinner />
        ) : modelsError ? (
            <LemonBanner
                type="error"
                action={{
                    children: 'Retry',
                    onClick: () => loadModels(),
                    'data-attr': 'autoresearch-run-model-retry',
                }}
            >
                Couldn't load this run's model. Try again, and if it keeps happening contact support.
            </LemonBanner>
        ) : (
            <div className="text-muted text-sm">
                This run did not produce a model, so it has no feature importances.
            </div>
        )
    }
    const compareWithChampion = champion && champion.id !== model.id
    const changes = compareWithChampion
        ? featureChanges(model.model_explanation, champion.model_explanation)
        : { added: [], dropped: [] }
    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-3 @2xl:grid-cols-2">
                <FeatureImportanceChart
                    explanation={model.model_explanation}
                    header={`This run's model · ${ROLE_LABEL[model.role ?? AutoresearchModelRoleEnumApi.Challenger]} · ${holdoutLabel(model)}`}
                    addedFeatures={changes.added}
                    droppedFeatures={changes.dropped}
                />
                {compareWithChampion && (
                    <FeatureImportanceChart
                        explanation={champion.model_explanation}
                        header={`Current champion · ${holdoutLabel(champion)}`}
                    />
                )}
            </div>
        </div>
    )
}
