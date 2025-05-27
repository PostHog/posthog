import { IconInfo } from '@posthog/icons'
import { LemonDivider, Tooltip } from '@posthog/lemon-ui'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import {
    ResponseSummariesButton,
    ResponseSummariesDisplay,
} from 'scenes/surveys/components/question-visualizations/OpenQuestionSummarizer'
import { OpenQuestionProcessedData } from 'scenes/surveys/surveyLogic'

import { BasicSurveyQuestion } from '~/types'

interface Props {
    question: BasicSurveyQuestion
    questionIndex: number
    processedData: OpenQuestionProcessedData
}

/**
 * SingleChoiceQuestionViz displays a pie chart for single choice questions
 * using a single optimized query to fetch all survey results at once
 */
export function OpenQuestionViz({
    question,
    questionIndex,
    processedData: { data, total },
}: Props): JSX.Element | null {
    if (!data || !total) {
        return <div>No responses yet</div>
    }

    // get a sample of 20 responses, random
    const randomSample = [...data].sort(() => Math.random() - 0.5).slice(0, 20)

    return (
        <div className="flex flex-col gap-2">
            <div>
                <div className="flex flex-row justify-between items-center">
                    <Tooltip title="See all Open Text responses in the Events table at the bottom.">
                        <div className="inline-flex gap-1">
                            <div className="font-semibold text-secondary">Open text</div>
                            <LemonDivider vertical className="my-1 mx-1" />
                            <div className="font-semibold text-secondary">random selection</div>
                            <IconInfo className="text-lg text-secondary shrink-0 ml-0.5 mt-0.5" />
                        </div>
                    </Tooltip>
                    <ResponseSummariesButton questionIndex={questionIndex} questionId={question.id} />
                </div>
                <div className="text-xl font-bold">
                    Question {questionIndex + 1}: {question.question}
                </div>
            </div>

            <ResponseSummariesDisplay />
            <div className="masonry-container">
                {randomSample.map((event, i) => {
                    const personProp = {
                        distinct_id: event.distinctId,
                        properties: event.personProperties,
                    }

                    return (
                        <div key={`open-text-${questionIndex}-${i}`} className="masonry-item border rounded">
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
        </div>
    )
}
