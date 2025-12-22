import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight, IconExternal } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightQueryNode } from '~/queries/schema/schema-general'

import { QUERY_TYPES_METADATA } from '../saved-insights/SavedInsights'
import { InsightSuggestion, insightAIAnalysisLogic } from './insightAIAnalysisLogic'

export interface InsightDiveDeeperSectionProps {
    insightId: number
    query: InsightQueryNode
}

function DiveDeeperRow({ suggestion }: { suggestion: InsightSuggestion }): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const InsightIcon = QUERY_TYPES_METADATA[suggestion.targetQuery.source.kind]?.icon

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
                    <div className="flex justify-end p-3 border-t border-border">
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

export function InsightDiveDeeperSection({ insightId, query }: InsightDiveDeeperSectionProps): JSX.Element | null {
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
                    <DiveDeeperRow key={index} suggestion={suggestion} />
                ))}
            </div>
        </div>
    )
}
