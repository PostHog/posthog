import { ResponseSummariesDisplay } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummarizer'
import { ResponseCard, ScrollToSurveyResultsCard } from 'scenes/surveys/components/question-visualizations/ResponseCard'

import { BasicSurveyQuestion, OpenQuestionResponseData } from '~/types'

interface Props {
    question: BasicSurveyQuestion
    responseData: OpenQuestionResponseData[]
}

export function OpenQuestionViz({ question, responseData }: Props): JSX.Element | null {
    return (
        <div className="space-y-4">
            <ResponseSummariesDisplay />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {responseData.slice(0, responseData.length > 20 ? 19 : 20).map((event, i) => (
                    <ResponseCard
                        key={`${question.id}-${i}`}
                        response={event.response}
                        distinctId={event.distinctId}
                        personProperties={event.personProperties}
                        timestamp={event.timestamp}
                    />
                ))}
                {responseData.length > 20 && <ScrollToSurveyResultsCard numOfResponses={responseData.length - 20} />}
            </div>
        </div>
    )
}
