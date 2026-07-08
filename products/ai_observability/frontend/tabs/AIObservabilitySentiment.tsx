import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPlus, IconRefresh } from '@posthog/icons'
import { LemonButton, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { urls } from 'scenes/urls'

import { MessageSentimentBar, SENTIMENT_BAR_COLOR } from '../components/SentimentTag'
import { normalizeMessages } from '../messageNormalization'
import { extractContentText, formatScore } from '../sentimentUtils'
import type { SentimentLabel } from '../sentimentUtils'
import type { CompatMessage } from '../types'
import { getTraceTimestamp } from '../utils'
import type { GroupedSentimentCard, SentimentCard, SentimentCategory } from './aiObservabilitySentimentLogic'
import { CLASSIFIER_WINDOW, aiObservabilitySentimentLogic } from './aiObservabilitySentimentLogic'

/**
 * Truncates long text to show start + end with an ellipsis in the middle.
 * Shows the head and tail so users can identify the message at a glance.
 */
function truncateMiddle(text: string, maxChars: number = 500): string {
    if (text.length <= maxChars) {
        return text
    }
    const half = Math.floor(maxChars / 2)
    return text.slice(0, half) + ' … ' + text.slice(-half)
}

/**
 * Retrieves the message at the given index from the raw $ai_input array.
 * The index corresponds to the position in the original messages array
 * (as used by the backend sentiment classifier).
 */
function getMessageAtIndex(aiInput: unknown, index: number): CompatMessage | null {
    try {
        const parsed = typeof aiInput === 'string' ? JSON.parse(aiInput) : aiInput
        if (!Array.isArray(parsed) || index < 0 || index >= parsed.length) {
            return null
        }
        const normalized = normalizeMessages([parsed[index]], 'user').messages
        return normalized[0] ?? null
    } catch {
        return null
    }
}

function getTextContent(message: CompatMessage): string {
    if (typeof message.content === 'string') {
        // Detect JSON-encoded structured content (e.g. '{"content":[{"text":"..."}]}')
        const trimmed = message.content.trim()
        if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
            try {
                const parsed = JSON.parse(trimmed)
                const extracted = extractContentText(parsed)
                if (extracted) {
                    return extracted
                }
            } catch {
                // Not valid JSON, return as-is
            }
        }
        return message.content
    }
    return extractContentText(message.content)
}

function ContextMessage({ aiInput, index }: { aiInput: unknown; index: number }): JSX.Element | null {
    const message = getMessageAtIndex(aiInput, index)
    if (!message) {
        return null
    }
    const role = message.role === 'user' ? 'User' : message.role === 'assistant' ? 'Assistant' : message.role
    const fullText = getTextContent(message)
    const displayText = truncateMiddle(fullText, 150)
    return (
        <div className="flex gap-2 text-xs text-muted py-1.5">
            <span className="shrink-0 font-medium w-16">{role}</span>
            <Tooltip title={fullText}>
                <span className="break-words min-w-0">{displayText || '(empty)'}</span>
            </Tooltip>
        </div>
    )
}

function SentimentCardRow({
    card,
    expanded,
    traceCount,
}: {
    card: SentimentCard
    expanded: boolean
    traceCount: number
}): JSX.Element {
    const { generation, messageIndex, sentiment } = card
    const { uuid, traceId, aiInput, timestamp, createdAt } = generation
    const { toggleCardExpanded, trackTraceClicked } = useActions(aiObservabilitySentimentLogic)

    const targetMessage = getMessageAtIndex(aiInput, messageIndex)
    const fullText = targetMessage ? getTextContent(targetMessage) : ''
    // The classifier only sees the last CLASSIFIER_WINDOW chars — show that slice
    const classifierText = fullText.slice(-CLASSIFIER_WINDOW)
    const collapsedText = truncateMiddle(classifierText)
    const accentColor = SENTIMENT_BAR_COLOR[sentiment.label as SentimentLabel] ?? 'bg-border'

    return (
        <div
            className="group/card flex border rounded-lg overflow-hidden cursor-pointer hover:border-primary/30 transition-colors bg-surface-primary"
            data-attr="llma-sentiment-card"
            onClick={() => toggleCardExpanded(`${uuid}:${messageIndex}`)}
        >
            <div className={`w-1 shrink-0 ${accentColor}`} />

            <div className="flex-1 min-w-0 p-3">
                {expanded && messageIndex > 0 && (
                    <div className="border-b mb-2 pb-2">
                        <ContextMessage aiInput={aiInput} index={messageIndex - 1} />
                    </div>
                )}

                <div className="flex items-start gap-2">
                    <p className="flex-1 min-w-0 text-sm text-default m-0 break-words leading-relaxed">
                        {expanded ? classifierText : collapsedText}
                    </p>
                    <div className="shrink-0 flex items-center gap-1">
                        {traceCount > 1 && (
                            <Tooltip title={`${traceCount} traces contain this same message`}>
                                <span className="inline-flex items-center text-xs font-medium text-muted bg-surface-tertiary rounded px-1.5 py-0.5 tabular-nums">
                                    {traceCount}x
                                </span>
                            </Tooltip>
                        )}
                        <MessageSentimentBar sentiment={sentiment} />
                        <span className="text-xs text-muted whitespace-nowrap tabular-nums">
                            {formatScore(sentiment.score)}
                        </span>
                        <span className="text-xs text-muted whitespace-nowrap ml-1">
                            <TZLabel time={timestamp} />
                        </span>
                        <Tooltip title="View the trace with this user message expanded">
                            <Link
                                to={urls.aiObservabilityTrace(traceId, {
                                    event: uuid,
                                    timestamp: getTraceTimestamp(createdAt),
                                    msg: String(messageIndex),
                                })}
                                className="text-xs ml-1"
                                data-attr="llma-sentiment-trace-link"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    trackTraceClicked(card)
                                }}
                            >
                                View trace
                            </Link>
                        </Tooltip>
                    </div>
                </div>

                {expanded && (
                    <div className="border-t mt-2 pt-2">
                        <ContextMessage aiInput={aiInput} index={messageIndex + 1} />
                        {!getMessageAtIndex(aiInput, messageIndex + 1) && (
                            <span className="text-xs text-muted italic">No following message</span>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}

const CATEGORY_CONFIG: { value: SentimentCategory; label: string; activeClass: string }[] = [
    { value: 'positive', label: 'Positive', activeClass: 'bg-success/20 border-success' },
    { value: 'negative', label: 'Negative', activeClass: 'bg-danger/20 border-danger' },
    { value: 'neutral', label: 'Neutral', activeClass: 'bg-border/20 border-border' },
]

function SentimentControls(): JSX.Element {
    const { activeFilters, intensityThreshold, sentimentSummary, generationsLoading } =
        useValues(aiObservabilitySentimentLogic)
    const { toggleSentimentCategory, setIntensityThreshold, loadGenerations } =
        useActions(aiObservabilitySentimentLogic)
    const total = sentimentSummary.positive + sentimentSummary.negative + sentimentSummary.neutral

    return (
        <div className="flex items-center gap-4 flex-wrap mb-3" data-attr="llma-sentiment-controls">
            <div className="flex items-center gap-2">
                <Tooltip title="Filter by sentiment polarity. Each user message is classified as positive, negative, or neutral.">
                    <span className="text-sm font-medium">Show:</span>
                </Tooltip>
                <div className="flex items-center gap-1" data-attr="llma-sentiment-filter">
                    {CATEGORY_CONFIG.map(({ value, label, activeClass }) => {
                        const isActive = activeFilters.has(value)
                        const count = sentimentSummary[value]
                        return (
                            <LemonButton
                                key={value}
                                size="small"
                                type="secondary"
                                className={isActive ? activeClass : 'opacity-50'}
                                onClick={() => toggleSentimentCategory(value)}
                                data-attr={`llma-sentiment-filter-${value}`}
                            >
                                {label}
                                {count > 0 && <span className="text-xs text-muted ml-1 tabular-nums">({count})</span>}
                            </LemonButton>
                        )
                    })}
                </div>
                {total > 0 && !generationsLoading && (
                    <Tooltip
                        title={`${sentimentSummary.positive} positive, ${sentimentSummary.negative} negative, ${sentimentSummary.neutral} neutral messages across all sentiment evaluation results`}
                    >
                        <span className="text-xs text-muted tabular-nums ml-1">{total} total</span>
                    </Tooltip>
                )}
            </div>
            <div className="flex items-center gap-2">
                <Tooltip title="Only show messages with a sentiment confidence score at or above this threshold. Higher values surface stronger signals. Does not apply to neutral messages.">
                    <span className="text-sm font-medium whitespace-nowrap">Min intensity:</span>
                </Tooltip>
                <LemonSlider
                    min={0}
                    max={1}
                    step={0.05}
                    value={intensityThreshold}
                    onChange={setIntensityThreshold}
                    className="w-24"
                />
                <span className="text-xs text-muted w-8 tabular-nums">{formatScore(intensityThreshold)}</span>
            </div>
            <div className="flex-1" />
            <LemonButton
                icon={<IconRefresh />}
                size="small"
                type="secondary"
                onClick={loadGenerations}
                loading={generationsLoading}
                data-attr="llma-sentiment-reload"
            >
                Reload
            </LemonButton>
        </div>
    )
}

function SentimentEvaluationOnboarding(): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center text-center py-20 text-muted">
            <p className="text-lg font-medium mb-1 text-default">Create a sentiment evaluation</p>
            <p className="text-sm max-w-xl mb-4">
                This tab shows stored sentiment evaluation results from your AI generation events. Create a sentiment
                evaluation to start classifying user-message sentiment for matching generations.
            </p>
            <LemonButton
                type="primary"
                icon={<IconPlus />}
                to={combineUrl(urls.aiObservabilityEvaluation('new'), { type: 'sentiment' }).url}
                data-attr="llma-sentiment-create-evaluation"
            >
                Create sentiment evaluation
            </LemonButton>
        </div>
    )
}

export function AIObservabilitySentiment(): JSX.Element {
    const {
        generations,
        generationsLoading,
        generationsError,
        sentimentEvaluationsLoading,
        hasLoadedSentimentEvaluations,
        showSentimentEvaluationOnboarding,
        groupedSentimentCards,
        sentimentCards,
        expandedCardIds,
        hasMore,
    } = useValues(aiObservabilitySentimentLogic)
    const { loadMoreGenerations } = useActions(aiObservabilitySentimentLogic)

    if (sentimentEvaluationsLoading || !hasLoadedSentimentEvaluations) {
        return (
            <div className="flex items-center justify-center py-20" data-attr="llma-sentiment-tab">
                <Spinner className="text-4xl" captureTime />
            </div>
        )
    }

    if (showSentimentEvaluationOnboarding) {
        return (
            <div data-attr="llma-sentiment-tab">
                <SentimentEvaluationOnboarding />
            </div>
        )
    }

    return (
        <div data-attr="llma-sentiment-tab">
            <SentimentControls />

            {generationsLoading && generations.length === 0 ? (
                <div className="flex items-center justify-center py-20">
                    <Spinner className="text-4xl" captureTime />
                </div>
            ) : generationsError ? (
                <div className="text-center py-20 text-muted">
                    <p className="text-lg font-medium mb-1">Failed to load generations</p>
                    <p className="text-sm">There was an error fetching data. Try refreshing the page.</p>
                </div>
            ) : generations.length === 0 ? (
                <div className="text-center py-20 text-muted">
                    <p className="text-lg font-medium mb-1">No sentiment evaluation results found</p>
                    <p className="text-sm">Try changing the date range or filters, or wait for matching generations.</p>
                </div>
            ) : (
                <>
                    {groupedSentimentCards.length > 0 && (
                        <div className="space-y-2">
                            {groupedSentimentCards.map((group: GroupedSentimentCard) => (
                                <SentimentCardRow
                                    key={`${group.card.generation.uuid}:${group.card.messageIndex}`}
                                    card={group.card}
                                    expanded={expandedCardIds.has(
                                        `${group.card.generation.uuid}:${group.card.messageIndex}`
                                    )}
                                    traceCount={group.traceCount}
                                />
                            ))}
                        </div>
                    )}

                    {generationsLoading && (
                        <div className="flex items-center justify-center py-8 gap-2 text-muted">
                            <Spinner className="text-lg" />
                            <span className="text-sm">Loading sentiment evaluation results…</span>
                        </div>
                    )}

                    {!generationsLoading && sentimentCards.length === 0 && (
                        <div className="text-center py-10 text-muted">
                            <p className="text-sm">
                                No sentiment evaluation results match the current filter. Try adjusting the controls
                                above.
                            </p>
                        </div>
                    )}

                    {!generationsLoading && hasMore && (
                        <div className="flex justify-center py-4">
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={loadMoreGenerations}
                                data-attr="llma-sentiment-load-more"
                            >
                                Load more
                            </LemonButton>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
