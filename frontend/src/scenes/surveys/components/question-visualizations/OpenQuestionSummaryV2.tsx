import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useEffect, useState } from 'react'

import {
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

interface SummaryData {
    content: string
    responseCount: number
    generatedAt: string
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
    const [rating, setRating] = useState<'good' | 'bad' | null>(null)
    const [showConsentPopover, setShowConsentPopover] = useState(false)

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

    const submitRating = (newRating: 'good' | 'bad'): void => {
        if (rating) {
            return
        }
        setRating(newRating)
        posthog.capture('ai_survey_summary_rated', {
            survey_id: survey.id,
            question_id: questionId,
            answer_rating: newRating,
        })
    }

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
                        <AIConsentPopoverWrapper showArrow onDismiss={handleDismissPopover}>
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
        <div className="border rounded p-4 mb-2 bg-surface-primary">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                    <IconSparkles className="text-warning" />
                    <span className="font-semibold">Response summary</span>
                </div>
                <div className="flex items-center gap-2">
                    {needsRefresh && (
                        <span className="text-xs text-muted">
                            {totalResponses - summary.responseCount} new responses
                        </span>
                    )}
                    {dataProcessingAccepted || !showConsentPopover ? (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconRefresh />}
                            onClick={handleRegenerateClick}
                            loading={loading}
                            tooltip="Regenerate summary"
                        />
                    ) : (
                        <AIConsentPopoverWrapper showArrow onDismiss={handleDismissPopover}>
                            <LemonButton
                                type="tertiary"
                                size="small"
                                icon={<IconRefresh />}
                                onClick={handleRegenerateClick}
                                loading={loading}
                                tooltip="Regenerate summary"
                            />
                        </AIConsentPopoverWrapper>
                    )}
                </div>
            </div>

            <div className="prose prose-sm max-w-none">
                <LemonMarkdown>{summary.content}</LemonMarkdown>
            </div>

            <div className="flex items-center justify-between mt-2 pt-2 border-t text-xs text-muted">
                <span>
                    Based on {summary.responseCount} responses
                    {generatedTime.isValid() && ` • Generated ${generatedTime.fromNow()}`}
                </span>
                <div className="flex items-center gap-1">
                    {rating === null && <span>Was this helpful?</span>}
                    {rating !== 'bad' && (
                        <LemonButton
                            icon={rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                            type="tertiary"
                            size="xsmall"
                            tooltip="Good summary"
                            onClick={() => submitRating('good')}
                        />
                    )}
                    {rating !== 'good' && (
                        <LemonButton
                            icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                            type="tertiary"
                            size="xsmall"
                            tooltip="Bad summary"
                            onClick={() => submitRating('bad')}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
