import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Button, Empty, EmptyContent, EmptyHeader, EmptyTitle, Skeleton, Text } from '@posthog/quill'

import { QuillBulkAcceptSuggestionsDialog } from 'products/warehouse_suggestions/frontend/components/QuillBulkAcceptSuggestionsDialog'
import { QuillBulkDismissSuggestionsDialog } from 'products/warehouse_suggestions/frontend/components/QuillBulkDismissSuggestionsDialog'
import { QuillDeprecateSuggestionModal } from 'products/warehouse_suggestions/frontend/components/QuillDeprecateSuggestionModal'
import { QuillMaterializeSuggestionModal } from 'products/warehouse_suggestions/frontend/components/QuillMaterializeSuggestionModal'
import { QuillSuggestedModelsGroups } from 'products/warehouse_suggestions/frontend/components/QuillSuggestedModelsGroups'
import { QuillSuggestionsReadsNote } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsReadsNote'
import { QuillSuggestionsStatusNotice } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsStatusNotice'
import { QuillSuggestionsSummary } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsSummary'
import { QuillUnmaterializeSuggestionModal } from 'products/warehouse_suggestions/frontend/components/QuillUnmaterializeSuggestionModal'
import { useFocusFollowsRemovedRow } from 'products/warehouse_suggestions/frontend/components/useFocusFollowsRemovedRow'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'
import { warehouseSuggestionsSectionLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsSectionLogic'

import { CatalogSuggestionCheckbox } from './CatalogSuggestionCheckbox'
import { CatalogSuggestionsBulkBar } from './CatalogSuggestionsBulkBar'
import { CatalogSuggestionsEmptyState } from './CatalogSuggestionsEmptyState'
import { catalogSuggestionsLogicProps } from './catalogSuggestionsLogicProps'
import { CatalogSuggestionsSelectAll } from './CatalogSuggestionsSelectAll'
import { CatalogSuggestionsToolbar } from './CatalogSuggestionsToolbar'

const NOTICE_STATES = ['error', 'warming_up', 'not_eligible']

function NoMatchingSuggestions(): JSX.Element {
    const { clearFilters } = useActions(warehouseSuggestionsSectionLogic)
    return (
        <Empty className="py-8">
            <EmptyHeader>
                <EmptyTitle>No suggestions match these filters</EmptyTitle>
            </EmptyHeader>
            <EmptyContent>
                <Button variant="outline" onClick={clearFilters} data-attr="data-catalog-suggestions-clear-filters">
                    Clear filters
                </Button>
            </EmptyContent>
        </Empty>
    )
}

function SuggestionsList(): JSX.Element {
    const { stripState, listedSuggestions, status } = useValues(warehouseSuggestionsLogic)
    const { filteredGroups, selectedSuggestions } = useValues(warehouseSuggestionsSectionLogic)
    const listRef = useRef<HTMLDivElement>(null)
    useFocusFollowsRemovedRow(
        listRef,
        listedSuggestions.map((suggestion) => suggestion.id),
        () => listRef.current?.querySelector<HTMLElement>('[data-suggestions-done]')?.focus()
    )

    return (
        <div ref={listRef} className="flex flex-col gap-3">
            {listedSuggestions.length > 0 && (
                <>
                    <CatalogSuggestionsToolbar />
                    {filteredGroups.length > 0 ? (
                        <div className="@container/suggestions divide-y divide-border rounded border border-border">
                            <CatalogSuggestionsSelectAll />
                            <QuillSuggestedModelsGroups
                                groups={filteredGroups}
                                windowDays={status?.window_days ?? 0}
                                renderSelection={(suggestion) => <CatalogSuggestionCheckbox suggestion={suggestion} />}
                            />
                        </div>
                    ) : (
                        <NoMatchingSuggestions />
                    )}
                </>
            )}
            {stripState !== 'active' && <CatalogSuggestionsEmptyState />}
            {selectedSuggestions.length > 0 && <CatalogSuggestionsBulkBar />}
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
            <QuillBulkAcceptSuggestionsDialog />
            <QuillBulkDismissSuggestionsDialog />
        </>
    )
}

export function CatalogSuggestionsSection(): JSX.Element {
    return (
        <section aria-label="Suggestions" className="flex flex-col gap-3" data-attr="data-catalog-suggestions">
            <BindLogic logic={warehouseSuggestionsSectionLogic} props={catalogSuggestionsLogicProps('suggestions')}>
                <SuggestionsContent />
            </BindLogic>
        </section>
    )
}
