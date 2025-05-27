import { IconInfo } from '@posthog/icons'
import { LemonDivider, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { MultipleChoiceQuestionViz } from 'scenes/surveys/components/question-visualizations/MultipleChoiceQuestionViz'
import { ResponseSummariesButton } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummarizer'
import { OpenQuestionViz } from 'scenes/surveys/components/question-visualizations/OpenQuestionViz'
import { SurveyQuestionLabel } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { SurveyQuestion, SurveyQuestionType } from '~/types'

import { RatingQuestionViz } from './RatingQuestionViz'
import { SingleChoiceQuestionViz } from './SingleChoiceQuestionViz'

/**
 * SurveyQuestionVisualization is a smart component that renders the appropriate
 * visualization based on the question type.
 *
 * It uses the optimized data loading approach that makes a single API query for all questions.
 */

interface Props {
    question: SurveyQuestion
    questionIndex: number
}

const SCALE_LABEL: Record<number, string> = {
    3: '1 - 3',
    5: '1 - 5',
    7: '1 - 7',
    10: '0 - 10',
}

function QuestionTitle({ question, questionIndex, totalResponses }: Props & { totalResponses: number }): JSX.Element {
    return (
        <div className="flex flex-col">
            <div className="inline-flex gap-1 max-w-fit font-semibold text-secondary items-center">
                <span>
                    {SurveyQuestionLabel[question.type]}&nbsp;
                    {question.type === SurveyQuestionType.Rating && <span>{SCALE_LABEL[question.scale]}</span>}
                </span>
                <LemonDivider vertical className="my-1 mx-1" />
                <span>{totalResponses} responses</span>
                {question.type === SurveyQuestionType.Open && (
                    <>
                        <LemonDivider vertical className="my-1 mx-1" />
                        <Tooltip title="See all Open Text responses in the Events table at the bottom.">
                            <span>random selection</span>
                            <IconInfo className="text-lg text-secondary shrink-0 ml-0.5 mt-0.5" />
                        </Tooltip>
                    </>
                )}
            </div>
            <div className="flex flex-row justify-between items-center">
                <h3 className="text-xl font-bold mb-0">
                    Question {questionIndex + 1}: {question.question}
                </h3>
                {question.type === SurveyQuestionType.Open && (
                    <ResponseSummariesButton questionIndex={questionIndex} questionId={question.id} />
                )}
            </div>
        </div>
    )
}

export function SurveyQuestionVisualization({ question, questionIndex }: Props): JSX.Element | null {
    const { consolidatedSurveyResults, consolidatedSurveyResultsLoading } = useValues(surveyLogic)

    if (!question.id || question.type === SurveyQuestionType.Link) {
        return null
    }

    if (consolidatedSurveyResultsLoading) {
        return <div>loading surveys data</div>
    }

    const processedData = consolidatedSurveyResults?.responsesByQuestion[question.id]

    if (!processedData || processedData.total === 0) {
        return <div>No responses yet in survey question viz</div>
    }

    /**
     *
     *
    {switch (question.type) {
        case SurveyQuestionType.Rating:
            return <RatingQuestionViz question={question} questionIndex={questionIndex} processedData={processedData} />
        case SurveyQuestionType.SingleChoice:
            return (
                <SingleChoiceQuestionViz
                    question={question}
                    questionIndex={questionIndex}
                    processedData={processedData}
                />
            )
        case SurveyQuestionType.MultipleChoice:
            return (
                <MultipleChoiceQuestionViz
                    question={question}
                    questionIndex={questionIndex}
                    processedData={processedData}
                />
            )
        case SurveyQuestionType.Open:
            return <OpenQuestionViz question={question} questionIndex={questionIndex} processedData={processedData} />
        default:
            return null
    }}
     */

    return (
        <div className="flex flex-col gap-2">
            <QuestionTitle
                question={question}
                questionIndex={questionIndex}
                totalResponses={processedData.totalResponses}
            />
            <ErrorBoundary className="m-0">
                {question.type === SurveyQuestionType.Rating && (
                    <RatingQuestionViz
                        question={question}
                        questionIndex={questionIndex}
                        processedData={processedData}
                    />
                )}
                {question.type === SurveyQuestionType.SingleChoice && (
                    <SingleChoiceQuestionViz question={question} processedData={processedData} />
                )}
                {question.type === SurveyQuestionType.MultipleChoice && (
                    <MultipleChoiceQuestionViz processedData={processedData} />
                )}
                {question.type === SurveyQuestionType.Open && (
                    <OpenQuestionViz question={question} processedData={processedData} />
                )}
            </ErrorBoundary>
        </div>
    )
}
