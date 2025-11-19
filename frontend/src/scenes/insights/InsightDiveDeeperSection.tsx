import { useActions } from 'kea'
import { router } from 'kea-router'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { InsightQueryNode } from '~/queries/schema/schema-general'

import { QUERY_TYPES_METADATA } from '../saved-insights/SavedInsights'
import { FollowUpSuggestion, getSuggestedFollowUps } from './utils/diveDeeperSuggestions'

export interface InsightDiveDeeperSectionProps {
    query: InsightQueryNode
}

const columns: LemonTableColumns<FollowUpSuggestion> = [
    {
        title: 'Suggested insight',
        key: 'title',
        render: (_, suggestion) => {
            const InsightIcon = QUERY_TYPES_METADATA[suggestion.targetQuery.source.kind]?.icon
            return (
                <div className="flex items-start gap-2 py-1">
                    {InsightIcon && <InsightIcon />}
                    <div className="flex flex-col">
                        <span className="font-semibold">{suggestion.title}</span>
                        {suggestion.description && (
                            <span className="text-muted text-xs mt-0.5">{suggestion.description}</span>
                        )}
                    </div>
                </div>
            )
        },
    },
]

export function InsightDiveDeeperSection({ query }: InsightDiveDeeperSectionProps): JSX.Element | null {
    const { push } = useActions(router)
    const suggestions = getSuggestedFollowUps(query)

    if (suggestions.length === 0) {
        return null
    }

    return (
        <div className="mt-4">
            <h2 className="font-semibold text-lg m-0 mb-2">Dive deeper</h2>
            <p className="text-muted mb-4">Explore related insights to understand your data better</p>

            <LemonTable
                showHeader={false}
                columns={columns}
                dataSource={suggestions}
                onRow={(suggestion) => ({
                    onClick: () => push(urls.insightNew({ query: suggestion.targetQuery })),
                })}
            />
        </div>
    )
}
