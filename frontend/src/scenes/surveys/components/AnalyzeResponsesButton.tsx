import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

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
        active: shouldShowMaxAnalysisTool,
        initialMaxPrompt: `Analyze the survey responses for the survey "${survey.name}"`,
    })
}

export function AnalyzeResponsesButton(): JSX.Element | null {
    const { openMax } = useSurveyAnalysisMaxTool()

    if (!openMax) {
        return null
    }

    return (
        <LemonButton onClick={openMax} type="secondary">
            Analyze responses
        </LemonButton>
    )
}
