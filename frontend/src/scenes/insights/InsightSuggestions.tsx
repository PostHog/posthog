import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight, IconExternal, IconThumbsDown, IconThumbsUp } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightQueryNode } from '~/queries/schema/schema-general'

import { QUERY_TYPES_METADATA } from '../saved-insights/SavedInsights'
import { InsightSuggestion, insightAIAnalysisLogic } from './insightAIAnalysisLogic'

export interface InsightSuggestionsProps {
    insightId: number
    query: InsightQueryNode
}

function InsightSuggestionRow({
    suggestion,
    index,
    insightId,
    query,
}: {
    suggestion: InsightSuggestion
    index: number
    insightId: number
    query: InsightQueryNode
}): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const InsightIcon = QUERY_TYPES_METADATA[suggestion.targetQuery.source.kind]?.icon
    const { reportSuggestionFeedback } = useActions(insightAIAnalysisLogic({ insightId, query }))
    const { suggestionFeedbackGiven } = useValues(insightAIAnalysisLogic({ insightId, query }))
    const feedbackGiven = suggestionFeedbackGiven[index]

    return (
        <div className="border border-border rounded bg-surface-primary">
            <div
                className="flex items-center gap-3 p-3 cursor-pointer hover:bg-surface-secondary rounded-t"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className={`transform transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                    <IconChevronRight className="text-xl" />
                </div>
                {InsightIcon && <InsightIcon className="text-secondary text-3xl" />}
                <div className="flex flex-col flex-1">
                    <span className="font-semibold">{suggestion.title}</span>
                    {suggestion.description && (
                        <span className="text-muted text-xs mt-0.5">{suggestion.description}</span>
                    )}
                </div>
            </div>
            {isExpanded && (
                <div className="border-t border-border bg-surface-primary">
                    <div className="p-4">
                        <Query query={suggestion.targetQuery} readOnly embedded />
                    </div>
                    <div className="flex justify-between items-center p-3 border-t border-border">
                        <div className="flex gap-2 items-center">
                            <span className="text-muted text-xs">
                                {feedbackGiven !== undefined
                                    ? 'Thanks for your feedback!'
                                    : 'Was this suggestion helpful?'}
                            </span>
                            <LemonButton
                                size="small"
                                icon={<IconThumbsUp />}
                                onClick={() => reportSuggestionFeedback(index, suggestion.title, true)}
                                tooltip="Helpful"
                                disabled={feedbackGiven !== undefined}
                                active={feedbackGiven === true}
                            />
                            <LemonButton
                                size="small"
                                icon={<IconThumbsDown />}
                                onClick={() => reportSuggestionFeedback(index, suggestion.title, false)}
                                tooltip="Not helpful"
                                disabled={feedbackGiven !== undefined}
                                active={feedbackGiven === false}
                            />
                        </div>
                        <LemonButton
                            type="primary"
                            icon={<IconExternal />}
                            to={urls.insightNew({ query: suggestion.targetQuery })}
                            targetBlank
                        >
                            Open in new tab
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

export function InsightSuggestions({ insightId, query }: InsightSuggestionsProps): JSX.Element | null {
    const { suggestions, suggestionsLoading } = useValues(insightAIAnalysisLogic({ insightId, query }))

    if (suggestionsLoading) {
        return (
            <div className="mt-4 flex items-center gap-2 text-muted">
                <Spinner className="text-xl" />
                <span>Generating suggestions...</span>
            </div>
        )
    }

    if (suggestions.length === 0) {
        return null
    }

    return (
        <div className="mt-4">
            <h3 className="font-semibold text-base m-0 mb-2">Explore related insights</h3>
            <p className="text-muted mb-4">Suggested follow-up insights to understand your data better</p>

            <div className="space-y-2">
                {suggestions.map((suggestion, index) => (
                    <InsightSuggestionRow
                        key={index}
                        suggestion={suggestion}
                        index={index}
                        insightId={insightId}
                        query={query}
                    />
                ))}
            </div>
        </div>
    )
}
