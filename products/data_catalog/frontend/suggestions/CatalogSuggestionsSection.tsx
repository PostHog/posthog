import { useValues } from 'kea'
import { useRef } from 'react'

import { Skeleton, Text } from '@posthog/quill'

import { QuillDeprecateSuggestionModal } from 'products/warehouse_suggestions/frontend/components/QuillDeprecateSuggestionModal'
import { QuillMaterializeSuggestionModal } from 'products/warehouse_suggestions/frontend/components/QuillMaterializeSuggestionModal'
import { QuillSuggestedModelsGroups } from 'products/warehouse_suggestions/frontend/components/QuillSuggestedModelsGroups'
import { QuillSuggestionsReadsNote } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsReadsNote'
import { QuillSuggestionsStatusNotice } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsStatusNotice'
import { QuillSuggestionsSummary } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsSummary'
import { QuillUnmaterializeSuggestionModal } from 'products/warehouse_suggestions/frontend/components/QuillUnmaterializeSuggestionModal'
import { useFocusFollowsRemovedRow } from 'products/warehouse_suggestions/frontend/components/useFocusFollowsRemovedRow'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { CatalogSuggestionsEmptyState } from './CatalogSuggestionsEmptyState'

const NOTICE_STATES = ['error', 'warming_up', 'not_eligible']

function SuggestionsList(): JSX.Element {
    const { stripState, suggestionGroups, listedSuggestions, status } = useValues(warehouseSuggestionsLogic)
    const listRef = useRef<HTMLDivElement>(null)
    useFocusFollowsRemovedRow(
        listRef,
        listedSuggestions.map((suggestion) => suggestion.id),
        () => listRef.current?.querySelector<HTMLElement>('[data-suggestions-done]')?.focus()
    )

    return (
        <div ref={listRef} className="flex flex-col gap-3">
            {listedSuggestions.length > 0 && (
                <div className="@container/suggestions divide-y divide-border rounded border border-border">
                    <QuillSuggestedModelsGroups groups={suggestionGroups} windowDays={status?.window_days ?? 0} />
                </div>
            )}
            {stripState !== 'active' && <CatalogSuggestionsEmptyState />}
        </div>
    )
}

function SuggestionsContent(): JSX.Element {
    const { stripState } = useValues(warehouseSuggestionsLogic)

    if (stripState === 'loading') {
        return <Skeleton className="h-40 w-full" aria-busy="true" />
    }
    if (NOTICE_STATES.includes(stripState)) {
        return <QuillSuggestionsStatusNotice />
    }
    return (
        <>
            {stripState === 'active' && (
                <Text size="sm" render={<div />}>
                    <QuillSuggestionsSummary />
                </Text>
            )}
            <SuggestionsList />
            <QuillSuggestionsReadsNote />
            <QuillMaterializeSuggestionModal />
            <QuillUnmaterializeSuggestionModal />
            <QuillDeprecateSuggestionModal />
        </>
    )
}

export function CatalogSuggestionsSection(): JSX.Element {
    return (
        <section aria-label="Suggestions" className="flex flex-col gap-3" data-attr="data-catalog-suggestions">
            <SuggestionsContent />
        </section>
    )
}
