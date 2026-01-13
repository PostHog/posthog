import { useValues } from 'kea'
import { useThumbSurvey } from 'posthog-js/react'
import { useCallback, useEffect, useState } from 'react'

import {
    IconChevronDown,
    IconRefresh,
    IconSparkles,
    IconThumbsDown,
    IconThumbsDownFilled,
    IconThumbsUp,
    IconThumbsUpFilled,
} from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

const MIN_RESPONSES_FOR_SUMMARY = 10
const NEW_RESPONSES_THRESHOLD = 5
const OPEN_QUESTION_SUMMARY_SURVEY_ID = '019bb5a3-1677-0000-63dd-00f241c1710a'

interface SummaryData {
    content: string
    responseCount: number
    generatedAt: string
    traceId?: string
    cached: boolean
}

interface OpenQuestionSummaryV2Props {
    questionId?: string
    questionIndex: number
    totalResponses: number
}

export function OpenQuestionSummaryV2({
    questionId,
    questionIndex,
    totalResponses,
}: OpenQuestionSummaryV2Props): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)

    const [summary, setSummary] = useState<SummaryData | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [showConsentPopover, setShowConsentPopover] = useState(false)
    const [isExpanded, setIsExpanded] = useState(true)

    const shouldShowSummary = totalResponses >= MIN_RESPONSES_FOR_SUMMARY
    const needsRefresh = summary && totalResponses - summary.responseCount >= NEW_RESPONSES_THRESHOLD

    const loadSummary = useCallback(
        async (forceRefresh: boolean = false) => {
            if (!survey.id || survey.id === 'new') {
                return
            }

            setLoading(true)
            setError(null)

            try {
                const result = await api.surveys.summarize_responses(survey.id, questionIndex, questionId, forceRefresh)
                setSummary({
                    content: result.content,
                    responseCount: result.response_count,
                    generatedAt: result.generated_at,
                    traceId: result.trace_id,
                    cached: result.cached,
                })
            } catch (e: any) {
                setError(e.message || 'Failed to generate summary')
            } finally {
                setLoading(false)
            }
        },
        [survey.id, questionId, questionIndex]
    )

    // Auto-load summary when conditions are met
    useEffect(() => {
        if (!shouldShowSummary || !dataProcessingAccepted) {
            return
        }

        // Only auto-load if we don't have a summary yet
        if (!summary && !loading) {
            loadSummary(false)
        }
    }, [shouldShowSummary, dataProcessingAccepted, summary, loading, loadSummary])

    const handleRegenerateClick = (): void => {
        if (!dataProcessingAccepted) {
            setShowConsentPopover(true)
        } else {
            loadSummary(true)
        }
    }

    const handleDismissPopover = (): void => {
        setShowConsentPopover(false)
    }
    const {
        respond: submitRating,
        response: rating,
        triggerRef,
    } = useThumbSurvey({
        surveyId: OPEN_QUESTION_SUMMARY_SURVEY_ID,
        properties: {
            customer_survey_id: survey.id,
            customer_question_id: questionId,
            $ai_trace_id: summary?.traceId,
        },
    })

    if (!shouldShowSummary) {
        return null
    }

    if (loading && !summary) {
        return (
            <div className="border rounded p-4 mb-4 bg-surface-primary">
                <div className="flex items-center gap-2 mb-3">
                    <IconSparkles className="text-warning" />
                    <span className="font-semibold">Response summary</span>
                </div>
                <div className="space-y-2">
                    <LemonSkeleton className="h-4 w-full" />
                    <LemonSkeleton className="h-4 w-3/4" />
                    <LemonSkeleton className="h-4 w-1/2" />
                </div>
            </div>
        )
    }

    if (error && !summary) {
        return (
            <div className="border rounded p-4 mb-2 bg-surface-primary border-danger">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-danger">
                        <IconSparkles />
                        <span>Failed to generate summary</span>
                    </div>
                    <LemonButton size="small" onClick={() => loadSummary(true)}>
                        Retry
                    </LemonButton>
                </div>
            </div>
        )
    }

    if (!summary) {
        // Waiting for consent or initial load
        if (!dataProcessingAccepted) {
            return (
                <div className="border rounded p-4 mb-2 bg-surface-primary">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <IconSparkles className="text-warning" />
                            <span className="font-semibold">Response summary</span>
                        </div>
                        <AIConsentPopoverWrapper
                            showArrow
                            onDismiss={handleDismissPopover}
                            hidden={!showConsentPopover}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconSparkles />}
                                onClick={() => setShowConsentPopover(true)}
                                disabledReason={dataProcessingApprovalDisabledReason}
                            >
                                Generate summary
                            </LemonButton>
                        </AIConsentPopoverWrapper>
                    </div>
                </div>
            )
        }
        return null
    }

    const generatedTime = dayjs(summary.generatedAt)

    return (
        <div className="border rounded mb-2 bg-surface-primary overflow-hidden">
            {/* Collapsible header */}
            <button
                type="button"
                className="w-full flex items-center justify-between p-3 hover:bg-surface-secondary transition-colors cursor-pointer"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className="flex items-center gap-2">
                    <IconSparkles className="text-warning" />
                    <span className="font-semibold">Response summary</span>
                    {!isExpanded && (
                        <span className="text-xs text-muted ml-2">Based on {summary.responseCount} responses</span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    {needsRefresh && (
                        <span className="text-xs text-muted">
                            {totalResponses - summary.responseCount} new responses
                        </span>
                    )}
                    <IconChevronDown
                        className={`transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
                    />
                </div>
            </button>

            {/* Collapsible content */}
            <div
                className={`transition-all duration-200 ease-in-out ${
                    isExpanded ? 'max-h-[1000px] opacity-100' : 'max-h-0 opacity-0 overflow-hidden'
                }`}
            >
                <div className="px-3 pb-3">
                    <div className="prose prose-sm max-w-none">
                        <LemonMarkdown>{summary.content}</LemonMarkdown>
                    </div>

                    <div className="flex items-center justify-between mt-3 pt-2 border-t text-xs text-muted">
                        <div className="flex items-center gap-2">
                            <span>
                                Based on {summary.responseCount}
                                {totalResponses > summary.responseCount
                                    ? ` of ${totalResponses} responses (sampled)`
                                    : ' responses'}
                                {generatedTime.isValid() && ` • ${generatedTime.fromNow()}`}
                                {' • AI-generated • Verify key details'}
                            </span>
                            {dataProcessingAccepted || !showConsentPopover ? (
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    icon={<IconRefresh />}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        handleRegenerateClick()
                                    }}
                                    loading={loading}
                                    tooltip="Regenerate summary"
                                />
                            ) : (
                                <AIConsentPopoverWrapper showArrow onDismiss={handleDismissPopover}>
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        icon={<IconRefresh />}
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            handleRegenerateClick()
                                        }}
                                        loading={loading}
                                        tooltip="Regenerate summary"
                                    />
                                </AIConsentPopoverWrapper>
                            )}
                        </div>
                        <div className="flex items-center gap-1" ref={triggerRef}>
                            {rating === null && <span>Was this helpful?</span>}
                            {rating !== 'down' && (
                                <LemonButton
                                    icon={rating === 'up' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                                    type="tertiary"
                                    size="xsmall"
                                    tooltip="Good summary"
                                    onClick={() => submitRating('up')}
                                />
                            )}
                            {rating !== 'up' && (
                                <LemonButton
                                    icon={rating === 'down' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                                    type="tertiary"
                                    size="xsmall"
                                    tooltip="Bad summary"
                                    onClick={() => submitRating('down')}
                                />
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
