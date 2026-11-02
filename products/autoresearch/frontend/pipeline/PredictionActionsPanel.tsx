import { useActions, useValues } from 'kea'

import { IconDecisionTree, IconFlag, IconGraph } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import {
    likelySegmentFeatureFlagUrl,
    likelySegmentWorkflowUrl,
    predictionBreakdownInsightUrl,
} from '../predictionSegments'
import { PersonPropertySetting } from './PersonPropertySetting'
import { SectionCard } from './SectionCard'

export function PredictionActionsPanel(): JSX.Element | null {
    const { pipeline, segmentThresholds, segmentDefinitions, personPropertyDisabledReason } =
        useValues(autoresearchPipelineLogic)
    const { reportPredictionLinkClicked } = useActions(autoresearchPipelineLogic)

    const outputProperty = pipeline?.output_person_property
    if (!pipeline || !outputProperty) {
        return null
    }
    const likelyRange = segmentDefinitions?.[0].probabilityRange.toLowerCase() ?? 'as likely'
    const segmentsLoading =
        personPropertyDisabledReason ?? (!segmentThresholds ? 'Segments are still loading' : undefined)

    return (
        <SectionCard
            title="Act on these predictions"
            description="Each link opens a prefilled draft. Review it, then save."
        >
            <PersonPropertySetting source="actions_panel" />
            <div className="flex flex-col gap-1">
                <LemonButton
                    icon={<IconFlag />}
                    to={segmentThresholds ? likelySegmentFeatureFlagUrl(outputProperty, segmentThresholds) : undefined}
                    disabledReason={segmentsLoading}
                    onClick={() => reportPredictionLinkClicked('feature_flag')}
                    data-attr="autoresearch-predictions-create-flag"
                    fullWidth
                >
                    Create a feature flag for people who score {likelyRange}
                </LemonButton>
                <LemonButton
                    icon={<IconDecisionTree />}
                    to={segmentThresholds ? likelySegmentWorkflowUrl(outputProperty, segmentThresholds) : undefined}
                    disabledReason={segmentsLoading}
                    onClick={() => reportPredictionLinkClicked('workflow')}
                    data-attr="autoresearch-predictions-create-workflow"
                    fullWidth
                >
                    Start a workflow for people who score {likelyRange}
                </LemonButton>
                <LemonButton
                    icon={<IconGraph />}
                    to={
                        personPropertyDisabledReason
                            ? undefined
                            : predictionBreakdownInsightUrl(pipeline, outputProperty)
                    }
                    disabledReason={personPropertyDisabledReason}
                    onClick={() => reportPredictionLinkClicked('insight')}
                    data-attr="autoresearch-predictions-create-insight"
                    fullWidth
                >
                    Chart {pipeline.target_event} by predicted probability
                </LemonButton>
            </div>
        </SectionCard>
    )
}
