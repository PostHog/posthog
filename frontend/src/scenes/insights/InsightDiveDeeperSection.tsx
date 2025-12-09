import { useState } from 'react'

import { IconChevronRight, IconExternal } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightQueryNode } from '~/queries/schema/schema-general'

import { QUERY_TYPES_METADATA } from '../saved-insights/SavedInsights'
import { FollowUpSuggestion, getSuggestedFollowUps } from './utils/diveDeeperSuggestions'

export interface InsightDiveDeeperSectionProps {
    query: InsightQueryNode
}

function DiveDeeperRow({ suggestion }: { suggestion: FollowUpSuggestion }): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const InsightIcon = QUERY_TYPES_METADATA[suggestion.targetQuery.source.kind]?.icon

    return (
        <div className="border border-border rounded bg-card">
            <div
                className="flex items-center gap-3 p-3 cursor-pointer hover:bg-surface-secondary rounded-t"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className={`transform transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                    <IconChevronRight className="text-xl" />
                </div>
                {InsightIcon && <InsightIcon className="text-muted-foreground text-3xl" />}
                <div className="flex flex-col flex-1">
                    <span className="font-semibold">{suggestion.title}</span>
                    {suggestion.description && (
                        <span className="text-muted-foreground text-xs mt-0.5">{suggestion.description}</span>
                    )}
                </div>
            </div>
            {isExpanded && (
                <div className="border-t border-border bg-card">
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

export function InsightDiveDeeperSection({ query }: InsightDiveDeeperSectionProps): JSX.Element | null {
    const suggestions = getSuggestedFollowUps(query)

    if (suggestions.length === 0) {
        return null
    }

    return (
        <div className="mt-4">
            <h2 className="font-semibold text-lg m-0 mb-2">Dive deeper</h2>
            <p className="text-muted-foreground mb-4">Explore related insights to understand your data better</p>

            <div className="space-y-2">
                {suggestions.map((suggestion, index) => (
                    <DiveDeeperRow key={index} suggestion={suggestion} />
                ))}
            </div>
        </div>
    )
}
