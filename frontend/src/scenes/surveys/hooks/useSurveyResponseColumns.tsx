import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconLlmAnalytics, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyResponse, isScaleTwoRating } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { QueryContextColumn } from '~/queries/types'
import { SurveyQuestionType } from '~/types'

const getTraceIdFromRecord = (record: unknown): string | null => {
    if (!Array.isArray(record)) {
        return null
    }
    const event = record[0] as { properties?: { $ai_trace_id?: string } } | undefined
    return event?.properties?.$ai_trace_id ?? null
}

export const getThumbIcon = (value: unknown): JSX.Element | null => {
    if (value == '1') {
        return <IconThumbsUp className="text-brand-blue" />
    }
    if (value == '2') {
        return <IconThumbsDown className="text-warning" />
    }
    return null
}

/**
 * Custom column renderers for the survey responses data table:
 * - Clamp long answers to 2 lines (full content available via row expansion).
 * - On the first question, surface a "View LLM trace" button when `$ai_trace_id` is present.
 * - On thumb questions, render the icon + "Thumbs up/down" instead of the raw `1`/`2` value.
 */
export function useSurveyResponseColumns(): Record<string, QueryContextColumn> {
    const { survey } = useValues(surveyLogic)

    return useMemo(() => {
        const columns: Record<string, QueryContextColumn> = {}

        survey.questions.forEach((question, index) => {
            const isThumb = isScaleTwoRating(question)
            const isFirstQuestion = index === 0
            const baseExpression = getSurveyResponse(question, index)
            // Must match the column expression built in surveyLogic.tsx so multi-choice
            // questions (wrapped in arrayStringConcat) also get matched.
            const columnName =
                question.type === SurveyQuestionType.MultipleChoice
                    ? `arrayStringConcat(${baseExpression}, ', ')`
                    : baseExpression

            columns[columnName] = {
                render: ({ value, record }) => {
                    const traceId = isFirstQuestion ? getTraceIdFromRecord(record) : null
                    const stringValue = value == null ? '' : String(value)

                    let displayContent: JSX.Element
                    if (isThumb && (value == '1' || value == '2')) {
                        displayContent = (
                            <span className="flex items-center gap-1">
                                {getThumbIcon(value)}
                                Thumbs {value == '1' ? 'up' : 'down'}
                            </span>
                        )
                    } else {
                        displayContent = <span className="whitespace-pre-wrap line-clamp-2">{stringValue}</span>
                    }

                    if (!traceId) {
                        return displayContent
                    }

                    return (
                        <span className="flex items-start gap-2 min-w-0">
                            <Tooltip title="View LLM trace">
                                <LemonButton
                                    size="xsmall"
                                    icon={
                                        <IconLlmAnalytics className="text-[var(--color-product-llm-analytics-light)]" />
                                    }
                                    to={urls.aiObservabilityTrace(traceId)}
                                />
                            </Tooltip>
                            <span className="min-w-0 flex-1">{displayContent}</span>
                        </span>
                    )
                },
            }
        })

        return columns
    }, [survey.questions])
}
