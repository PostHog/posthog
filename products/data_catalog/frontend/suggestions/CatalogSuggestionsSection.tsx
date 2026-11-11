import { BindLogic, useValues } from 'kea'
import { useRef } from 'react'

import { Skeleton, Text } from '@posthog/quill'

import { QuillDeprecateSuggestionModal } from 'products/warehouse_suggestions/frontend/components/QuillDeprecateSuggestionModal'
import { QuillMaterializeSuggestionModal } from 'products/warehouse_suggestions/frontend/components/QuillMaterializeSuggestionModal'
import { QuillSuggestedModelsGroups } from 'products/warehouse_suggestions/frontend/components/QuillSuggestedModelsGroups'
import { QuillSuggestionsCaughtUp } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsCaughtUp'
import { QuillSuggestionsReadsNote } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsReadsNote'
import { QuillSuggestionsStatusNotice } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsStatusNotice'
import { QuillSuggestionsSummary } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsSummary'
import { QuillUnmaterializeSuggestionModal } from 'products/warehouse_suggestions/frontend/components/QuillUnmaterializeSuggestionModal'
import { useFocusFollowsRemovedRow } from 'products/warehouse_suggestions/frontend/components/useFocusFollowsRemovedRow'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { catalogSuggestionsLogicProps } from './catalogSuggestionsLogicProps'

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
        <div ref={listRef} className="@container/suggestions rounded border border-border">
            <div className="divide-y divide-border">
                <QuillSuggestedModelsGroups groups={suggestionGroups} windowDays={status?.window_days ?? 0} />
            </div>
            {stripState !== 'active' && <QuillSuggestionsCaughtUp placement="section" />}
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
            <BindLogic logic={warehouseSuggestionsLogic} props={catalogSuggestionsLogicProps('suggestions_section')}>
                <SuggestionsContent />
            </BindLogic>
        </section>
    )
}
