import { OpenQuestionSummaryV2 } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummaryV2'
import { VirtualizedResponseList } from 'scenes/surveys/components/question-visualizations/VirtualizedResponseList'

import { BasicSurveyQuestion, OpenQuestionResponseData } from '~/types'

interface Props {
    question: BasicSurveyQuestion
    questionIndex: number
    responseData: OpenQuestionResponseData[]
    totalResponses: number
}

export function OpenQuestionViz({ question, questionIndex, responseData, totalResponses }: Props): JSX.Element | null {
    return (
        <div className="space-y-4">
            <OpenQuestionSummaryV2
                questionId={question.id}
                questionIndex={questionIndex}
                totalResponses={totalResponses}
            />
            <VirtualizedResponseList responses={responseData} />
        </div>
    )
}
