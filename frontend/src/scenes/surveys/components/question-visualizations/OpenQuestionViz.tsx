import { useValues } from 'kea'

import { ResponseSummariesDisplay } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummarizer'
import { OpenQuestionSummaryV2 } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummaryV2'
import { ResponseCard, ScrollToSurveyResultsCard } from 'scenes/surveys/components/question-visualizations/ResponseCard'
import { VirtualizedResponseList } from 'scenes/surveys/components/question-visualizations/VirtualizedResponseList'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { BasicSurveyQuestion, OpenQuestionResponseData } from '~/types'

interface Props {
    question: BasicSurveyQuestion
    questionIndex: number
    responseData: OpenQuestionResponseData[]
    totalResponses: number
}

function OpenQuestionVizV1({ question, responseData }: Omit<Props, 'questionIndex' | 'totalResponses'>): JSX.Element {
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

function OpenQuestionVizV2({ question, questionIndex, responseData, totalResponses }: Props): JSX.Element {
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

export function OpenQuestionViz({ question, questionIndex, responseData, totalResponses }: Props): JSX.Element | null {
    const { isSurveyResultsV2Enabled } = useValues(surveyLogic)

    if (isSurveyResultsV2Enabled) {
        return (
            <OpenQuestionVizV2
                question={question}
                questionIndex={questionIndex}
                responseData={responseData}
                totalResponses={totalResponses}
            />
        )
    }

    return <OpenQuestionVizV1 question={question} responseData={responseData} />
}
