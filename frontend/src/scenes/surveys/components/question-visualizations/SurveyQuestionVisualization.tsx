import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonDivider, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { StatelessInsightLoadingState } from 'scenes/insights/EmptyStates'
import { SurveyNoResponsesBanner } from 'scenes/surveys/SurveyNoResponsesBanner'
import { MultipleChoiceQuestionViz } from 'scenes/surveys/components/question-visualizations/MultipleChoiceQuestionViz'
import { ResponseSummariesButton } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummarizer'
import { OpenQuestionViz } from 'scenes/surveys/components/question-visualizations/OpenQuestionViz'
import { SurveyQuestionLabel } from 'scenes/surveys/constants'
import { QuestionProcessedResponses, surveyLogic } from 'scenes/surveys/surveyLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { SurveyQuestion, SurveyQuestionType } from '~/types'

import { SCALE_LABELS } from '../../constants'
import { NPSBreakdownSkeleton, RatingQuestionViz } from './RatingQuestionViz'
import { SingleChoiceQuestionViz } from './SingleChoiceQuestionViz'

interface Props {
    question: SurveyQuestion
    questionIndex: number
}

function QuestionTitle({
    question,
    questionIndex,
    totalResponses = 0,
}: Props & { totalResponses?: number }): JSX.Element {
    return (
        <div className="flex flex-col">
            <div className="text-secondary inline-flex max-w-fit items-center gap-1 font-semibold">
                <span>
                    {SurveyQuestionLabel[question.type]}&nbsp;
                    {question.type === SurveyQuestionType.Rating && (
                        <span>{SCALE_LABELS[question.scale] || `1 - ${question.scale}`}</span>
                    )}
                </span>
                {totalResponses > 0 && (
                    <>
                        <LemonDivider vertical className="mx-1 my-1" />
                        <span>{totalResponses} responses</span>
                        {question.type === SurveyQuestionType.Open && (
                            <>
                                <LemonDivider vertical className="mx-1 my-1" />
                                <Tooltip title="See all Open Text responses in the Events table at the bottom.">
                                    <span>random selection</span>
                                    <IconInfo className="text-secondary ml-0.5 mt-0.5 shrink-0 text-lg" />
                                </Tooltip>
                            </>
                        )}
                    </>
                )}
            </div>
            <div className="flex flex-row items-center justify-between">
                <h3 className="mb-0 text-xl font-bold">
                    Question {questionIndex + 1}: {question.question}
                </h3>
                {question.type === SurveyQuestionType.Open && totalResponses > 5 && (
                    <ResponseSummariesButton questionIndex={questionIndex} questionId={question.id} />
                )}
            </div>
        </div>
    )
}

function QuestionLoadingSkeleton({ question }: { question: SurveyQuestion }): JSX.Element {
    switch (question.type) {
        case SurveyQuestionType.Rating:
            return (
                <>
                    <div className="flex flex-col gap-1">
                        <div className="h-50 flex flex-col gap-2 rounded border p-4">
                            <div className="flex h-full items-end justify-between">
                                {Array.from({ length: question.scale || 5 }).map((_, i) => {
                                    // Use predefined height classes for variety
                                    const heights = ['h-4', 'h-8', 'h-12', 'h-16', 'h-20', 'h-24', 'h-28', 'h-32']
                                    const randomHeight = heights[Math.floor(Math.random() * heights.length)]
                                    return (
                                        <div key={i} className="flex flex-1 flex-col items-center gap-1">
                                            <LemonSkeleton className={`w-8 sm:w-12 ${randomHeight}`} />
                                            <span className="text-secondary text-sm font-semibold">{i + 1}</span>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                        <div className="flex flex-row justify-between">
                            <div className="text-secondary pl-10">{question.lowerBoundLabel}</div>
                            <div className="text-secondary pr-10">{question.upperBoundLabel}</div>
                        </div>
                    </div>
                    {question.scale === 10 && <NPSBreakdownSkeleton />}
                    <LemonSkeleton className="h-9 w-full" />
                </>
            )
        case SurveyQuestionType.SingleChoice:
            return (
                <div className="flex h-80 overflow-y-auto rounded border pb-2 pt-4">
                    <div className="relative flex h-full w-80 items-center justify-center">
                        <LemonSkeleton className="h-64 w-64 rounded-full" />
                    </div>
                    <div className="flex flex-1 flex-col justify-center space-y-3 px-6">
                        {question.choices.map((choice, i) => (
                            <div key={i} className="flex items-center gap-2">
                                <LemonSkeleton className="h-3 w-3 flex-shrink-0 rounded-full" />
                                <span className="text-secondary text-sm font-semibold">{choice}</span>
                                <LemonSkeleton className="h-4 w-8 flex-shrink-0" />
                            </div>
                        ))}
                    </div>
                </div>
            )
        case SurveyQuestionType.MultipleChoice:
            return (
                <div className="max-h-[600px] overflow-y-auto rounded border py-4">
                    <div className="flex flex-col gap-1">
                        {question.choices.map((choice, i) => {
                            // Use decreasing widths to match typical survey result ordering
                            const barWidths = ['w-11/12', 'w-3/4', 'w-3/5', 'w-1/2', 'w-2/5']
                            const width = barWidths[i] || 'w-1/4'
                            return (
                                <div key={i} className="flex items-center gap-4">
                                    <div className="text-secondary w-48 flex-shrink-0 truncate text-right text-xs">
                                        {choice}
                                    </div>
                                    <div className="flex flex-1 items-center gap-2">
                                        <LemonSkeleton className={`h-4 ${width}`} />
                                        <LemonSkeleton className="h-4 w-6 flex-shrink-0" />
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            )
        case SurveyQuestionType.Open:
            return (
                <div className="masonry-container">
                    {Array.from({ length: 8 }).map((_, i) => (
                        <div key={i} className="masonry-item rounded border">
                            <div className="flex flex-col items-center space-y-2 px-5 py-4">
                                <LemonSkeleton className="h-4 w-full" />
                                <LemonSkeleton className="h-4 w-3/4" />
                                <LemonSkeleton className="h-4 w-1/2" />
                            </div>
                            <div className="bg-surface-primary rounded-b border-t px-5 py-4">
                                <div className="flex items-center justify-center gap-2">
                                    <LemonSkeleton className="h-6 w-6 rounded-full" />
                                    <LemonSkeleton className="h-4 w-24" />
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )
        default:
            return (
                <div className="bg-surface-primary">
                    <StatelessInsightLoadingState />
                </div>
            )
    }
}

export function SurveyQuestionVisualization({ question, questionIndex }: Props): JSX.Element | null {
    const { consolidatedSurveyResults, consolidatedSurveyResultsLoading, surveyBaseStatsLoading } =
        useValues(surveyLogic)

    if (!question.id || question.type === SurveyQuestionType.Link) {
        return null
    }

    const processedData: QuestionProcessedResponses | undefined =
        consolidatedSurveyResults?.responsesByQuestion[question.id]

    if (consolidatedSurveyResultsLoading || surveyBaseStatsLoading || !processedData) {
        return (
            <div className="flex flex-col gap-2">
                <QuestionTitle question={question} questionIndex={questionIndex} />
                <div className="flex flex-col gap-4">
                    <QuestionLoadingSkeleton question={question} />
                </div>
            </div>
        )
    }

    if (processedData.totalResponses === 0 || processedData.data.length === 0) {
        return (
            <div className="flex flex-col gap-2">
                <QuestionTitle question={question} questionIndex={questionIndex} />
                <SurveyNoResponsesBanner type="question" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <QuestionTitle
                question={question}
                questionIndex={questionIndex}
                totalResponses={processedData.totalResponses}
            />
            <div className="flex flex-col gap-4">
                <ErrorBoundary className="m-0">
                    {question.type === SurveyQuestionType.Rating &&
                        processedData.type === SurveyQuestionType.Rating && (
                            <RatingQuestionViz
                                question={question}
                                questionIndex={questionIndex}
                                processedData={processedData}
                            />
                        )}
                    {question.type === SurveyQuestionType.SingleChoice &&
                        processedData.type === SurveyQuestionType.SingleChoice && (
                            <SingleChoiceQuestionViz question={question} processedData={processedData} />
                        )}
                    {question.type === SurveyQuestionType.MultipleChoice &&
                        processedData.type === SurveyQuestionType.MultipleChoice && (
                            <MultipleChoiceQuestionViz responseData={processedData.data} />
                        )}
                    {question.type === SurveyQuestionType.Open && processedData.type === SurveyQuestionType.Open && (
                        <OpenQuestionViz question={question} responseData={processedData.data} />
                    )}
                </ErrorBoundary>
            </div>
        </div>
    )
}
