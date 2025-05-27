import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { ResponseSummariesDisplay } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummarizer'
import { OpenQuestionProcessedData } from 'scenes/surveys/surveyLogic'

import { BasicSurveyQuestion } from '~/types'

interface Props {
    question: BasicSurveyQuestion
    processedData: OpenQuestionProcessedData
}

/**
 * SingleChoiceQuestionViz displays a pie chart for single choice questions
 * using a single optimized query to fetch all survey results at once
 */
export function OpenQuestionViz({ question, processedData: { data } }: Props): JSX.Element | null {
    if (!data.length) {
        return <div>No responses yet</div>
    }

    // get a sample of 20 responses, random
    const randomSample = [...data].sort(() => Math.random() - 0.5).slice(0, 20)

    return (
        <>
            <ResponseSummariesDisplay />
            <div className="masonry-container">
                {randomSample.map((event, i) => {
                    const personProp = {
                        distinct_id: event.distinctId,
                        properties: event.personProperties,
                    }

                    return (
                        <div key={`${question.id}-${i}`} className="masonry-item border rounded">
                            <div className="max-h-80 overflow-y-auto text-center italic font-semibold px-5 py-4">
                                {typeof event.response !== 'string' ? JSON.stringify(event.response) : event.response}
                            </div>
                            <div className="bg-surface-primary items-center px-5 py-4 border-t rounded-b truncate w-full">
                                <PersonDisplay person={personProp} withIcon={true} noEllipsis={false} isCentered />
                            </div>
                        </div>
                    )
                })}
            </div>
        </>
    )
}
