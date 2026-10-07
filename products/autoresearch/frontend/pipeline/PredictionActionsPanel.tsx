import { useActions, useValues } from 'kea'

import { IconDecisionTree, IconFlag, IconGraph } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import {
    PREDICTION_SEGMENTS,
    likelySegmentFeatureFlagUrl,
    likelySegmentWorkflowUrl,
    predictionBreakdownInsightUrl,
} from '../predictionSegments'

export function PredictionActionsPanel(): JSX.Element | null {
    const { pipeline } = useValues(autoresearchPipelineLogic)
    const { reportPredictionLinkClicked } = useActions(autoresearchPipelineLogic)

    const outputProperty = pipeline?.output_person_property
    if (!pipeline || !outputProperty) {
        return null
    }
    const likelyRange = PREDICTION_SEGMENTS[0].range.toLowerCase()

    return (
        <div className="border rounded p-4 bg-surface-primary">
            <h3 className="font-semibold mb-1">Act on these predictions</h3>
            <p className="text-sm text-secondary mb-3">
                Each link opens a prefilled draft. Review it, then save.
            </p>
            <div className="flex flex-col gap-1">
                <LemonButton
                    icon={<IconFlag />}
                    to={likelySegmentFeatureFlagUrl(outputProperty)}
                    onClick={() => reportPredictionLinkClicked('feature_flag')}
                    data-attr="autoresearch-predictions-create-flag"
                    fullWidth
                >
                    Create a feature flag for people who score {likelyRange}
                </LemonButton>
                <LemonButton
                    icon={<IconDecisionTree />}
                    to={likelySegmentWorkflowUrl(outputProperty)}
                    onClick={() => reportPredictionLinkClicked('workflow')}
                    data-attr="autoresearch-predictions-create-workflow"
                    fullWidth
                >
                    Start a workflow for people who score {likelyRange}
                </LemonButton>
                <LemonButton
                    icon={<IconGraph />}
                    to={predictionBreakdownInsightUrl(pipeline, outputProperty)}
                    onClick={() => reportPredictionLinkClicked('insight')}
                    data-attr="autoresearch-predictions-create-insight"
                    fullWidth
                >
                    Chart {pipeline.target_event} by predicted probability
                </LemonButton>
            </div>
        </div>
    )
}
