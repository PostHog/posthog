import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconAI } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

const NUM_OF_RESPONSES_FOR_MAX_ANALYSIS_TOOL = 5

function useSurveyAnalysisMaxTool(): ReturnType<typeof useMaxTool> {
    const { survey, isSurveyAnalysisMaxToolEnabled, formattedOpenEndedResponses } = useValues(surveyLogic)

    const maxToolContext = useMemo(
        () => ({
            survey_id: survey.id,
            survey_name: survey.name,
            formatted_responses: formattedOpenEndedResponses,
        }),
        [survey.id, survey.name, formattedOpenEndedResponses]
    )

    const shouldShowMaxAnalysisTool = useMemo(() => {
        if (!isSurveyAnalysisMaxToolEnabled) {
            return false
        }
        const totalResponses = formattedOpenEndedResponses.reduce((acc, curr) => acc + curr.responses.length, 0)
        return totalResponses >= NUM_OF_RESPONSES_FOR_MAX_ANALYSIS_TOOL
    }, [isSurveyAnalysisMaxToolEnabled, formattedOpenEndedResponses])

    return useMaxTool({
        identifier: 'analyze_survey_responses',
        context: maxToolContext,
        contextDescription: {
            text: survey.name,
            icon: iconForType('survey'),
        },
        active: shouldShowMaxAnalysisTool,
        initialMaxPrompt: `Analyze the survey responses for the survey "${survey.name}"`,
        callback(toolOutput) {
            addProductIntent({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_ANALYZED,
                metadata: {
                    survey_id: survey.id,
                },
            })

            if (toolOutput?.error) {
                posthog.captureException(
                    toolOutput?.error || 'Undefined error when analyzing survey responses with PostHog AI',
                    {
                        action: 'max-ai-survey-analysis-failed',
                        survey_id: survey.id,
                        ...toolOutput,
                    }
                )
            }
        },
    })
}

export function AnalyzeResponsesButton(): JSX.Element | null {
    const { openMax } = useSurveyAnalysisMaxTool()

    if (!openMax) {
        return null
    }

    return (
        <LemonButton onClick={openMax} type="secondary" icon={<IconAI />}>
            Analyze responses
        </LemonButton>
    )
}
