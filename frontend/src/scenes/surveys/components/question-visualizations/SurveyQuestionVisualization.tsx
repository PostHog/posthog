import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonDivider, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { StatelessInsightLoadingState } from 'scenes/insights/EmptyStates'
import { SurveyNoResponsesBanner } from 'scenes/surveys/SurveyNoResponsesBanner'
import { AnalyzeResponsesButton } from 'scenes/surveys/components/AnalyzeResponsesButton'
import { MultipleChoiceQuestionViz } from 'scenes/surveys/components/question-visualizations/MultipleChoiceQuestionViz'
import { ResponseSummariesButton } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummarizer'
import { OpenQuestionViz } from 'scenes/surveys/components/question-visualizations/OpenQuestionViz'
import { SurveyQuestionLabel } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { QuestionProcessedResponses, SurveyQuestion, SurveyQuestionType } from '~/types'

import { SCALE_LABELS } from '../../constants'
import { NPSBreakdownSkeleton, RatingQuestionViz } from './RatingQuestionViz'

interface Props {
    question: SurveyQuestion
    questionIndex: number
    demoData?: QuestionProcessedResponses // For demo mode
}

function QuestionTitle({
    question,
    questionIndex,
    totalResponses = 0,
}: Props & { totalResponses?: number }): JSX.Element {
    const { isSurveyAnalysisMaxToolEnabled } = useValues(surveyLogic)
    return (
        <div className="flex flex-col">
            <div className="inline-flex gap-1 max-w-fit font-semibold text-secondary items-center">
                <span>
                    {SurveyQuestionLabel[question.type]}&nbsp;
                    {question.type === SurveyQuestionType.Rating && (
                        <span>{SCALE_LABELS[question.scale] || `1 - ${question.scale}`}</span>
                    )}
                </span>
                {totalResponses > 0 && (
                    <>
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
                    </>
                )}
            </div>
            <div className="flex flex-row justify-between items-center">
                <h3 className="text-xl font-bold mb-0">
                    Question {questionIndex + 1}: {question.question}
                </h3>
                {question.type === SurveyQuestionType.Open && totalResponses > 5 && !isSurveyAnalysisMaxToolEnabled && (
                    <ResponseSummariesButton questionIndex={questionIndex} questionId={question.id} />
                )}
                {isSurveyAnalysisMaxToolEnabled && <AnalyzeResponsesButton />}
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
                        <div className="h-50 border rounded p-4 flex flex-col gap-2">
                            <div className="flex justify-between items-end h-full">
                                {Array.from({ length: question.scale === 10 ? 11 : question.scale || 5 }).map(
                                    (_, i) => {
                                        // Use predefined height classes for variety
                                        const heights = ['h-4', 'h-8', 'h-12', 'h-16', 'h-20', 'h-24', 'h-28', 'h-32']
                                        const randomHeight = heights[Math.floor(Math.random() * heights.length)]
                                        return (
                                            <div key={i} className="flex flex-col items-center gap-1 flex-1">
                                                <LemonSkeleton className={`w-8 sm:w-12 ${randomHeight}`} />
                                                <span className="text-sm text-secondary font-semibold">
                                                    {question.scale === 10 ? i : i + 1}
                                                </span>
                                            </div>
                                        )
                                    }
                                )}
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
        case SurveyQuestionType.MultipleChoice:
            return (
                <div className="border rounded py-4 max-h-[600px] overflow-y-auto">
                    <div className="flex flex-col gap-3">
                        {question.choices.map((choice, i) => {
                            // Use decreasing widths to match typical survey result ordering
                            const barWidths = ['w-11/12', 'w-3/4', 'w-3/5', 'w-1/2', 'w-2/5']
                            const width = barWidths[i] || 'w-1/4'
                            return (
                                <div key={i} className="flex items-center gap-6">
                                    <div className="w-48 text-right text-sm text-secondary flex-shrink-0 truncate">
                                        {choice}
                                    </div>
                                    <div className="flex-1 flex items-center gap-2">
                                        <LemonSkeleton className={`h-6 ${width}`} />
                                        <LemonSkeleton className="w-6 h-6 flex-shrink-0" />
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
                        <div key={i} className="masonry-item border rounded">
                            <div className="px-5 py-4 space-y-2 flex flex-col items-center">
                                <LemonSkeleton className="h-4 w-full" />
                                <LemonSkeleton className="h-4 w-3/4" />
                                <LemonSkeleton className="h-4 w-1/2" />
                            </div>
                            <div className="bg-surface-primary px-5 py-4 border-t rounded-b">
                                <div className="flex items-center gap-2 justify-center">
                                    <LemonSkeleton className="w-6 h-6 rounded-full" />
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

export function SurveyQuestionVisualization({ question, questionIndex, demoData }: Props): JSX.Element | null {
    const { consolidatedSurveyResults, consolidatedSurveyResultsLoading, surveyBaseStatsLoading } =
        useValues(surveyLogic)

    if (demoData) {
        return (
            <div className="flex flex-col gap-2">
                <QuestionTitle
                    question={question}
                    questionIndex={questionIndex}
                    totalResponses={demoData.totalResponses}
                />
                <div className="flex flex-col gap-4">
                    {question.type === SurveyQuestionType.Rating && demoData.type === SurveyQuestionType.Rating && (
                        <RatingQuestionViz question={question} questionIndex={questionIndex} processedData={demoData} />
                    )}
                    {(question.type === SurveyQuestionType.SingleChoice ||
                        question.type === SurveyQuestionType.MultipleChoice) &&
                        (demoData.type === SurveyQuestionType.SingleChoice ||
                            demoData.type === SurveyQuestionType.MultipleChoice) && (
                            <MultipleChoiceQuestionViz responseData={demoData.data} />
                        )}
                    {question.type === SurveyQuestionType.Open && demoData.type === SurveyQuestionType.Open && (
                        <OpenQuestionViz question={question} responseData={demoData.data} />
                    )}
                </div>
            </div>
        )
    }

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
                    {(question.type === SurveyQuestionType.SingleChoice ||
                        question.type === SurveyQuestionType.MultipleChoice) &&
                        (processedData.type === SurveyQuestionType.SingleChoice ||
                            processedData.type === SurveyQuestionType.MultipleChoice) && (
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
