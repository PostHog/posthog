import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { ResponseSummariesDisplay } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummarizer'
import { OpenQuestionResponseData } from 'scenes/surveys/surveyLogic'

import { BasicSurveyQuestion } from '~/types'

interface Props {
    question: BasicSurveyQuestion
    responseData: OpenQuestionResponseData[]
}

export function OpenQuestionViz({ question, responseData }: Props): JSX.Element | null {
    return (
        <>
            <ResponseSummariesDisplay />
            <div className="masonry-container">
                {responseData.slice(0, 20).map((event, i) => {
                    const personProp = {
                        distinct_id: event.distinctId,
                        properties: event.personProperties,
                    }

                    return (
                        <div key={`${question.id}-${i}`} className="masonry-item border rounded">
                            <div className="max-h-80 overflow-y-auto text-center italic font-semibold px-5 py-4">
                                {typeof event.response !== 'string' ? JSON.stringify(event.response) : event.response}
                            </div>
                            <div className="bg-card items-center px-5 py-4 border-t rounded-b truncate w-full">
                                <PersonDisplay person={personProp} withIcon={true} noEllipsis={false} isCentered />
                            </div>
                        </div>
                    )
                })}
            </div>
        </>
    )
}
