import { useActions, useValues } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { DataTableNode } from '~/queries/schema/schema-general'

import { dataTableSavedFiltersLogic } from './dataTableSavedFiltersLogic'

export interface DataTableSavedFiltersButtonProps {
    uniqueKey: string
    query: DataTableNode
    setQuery: (query: DataTableNode) => void
}

export function DataTableSavedFiltersButton({
    uniqueKey,
    query,
    setQuery,
}: DataTableSavedFiltersButtonProps): JSX.Element {
    const logic = dataTableSavedFiltersLogic({ uniqueKey, query, setQuery })
    const { savedFilters, appliedSavedFilter, showSavedFilters } = useValues(logic)
    const { setShowSavedFilters } = useActions(logic)

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconBookmark />}
                sideIcon={
                    savedFilters.length > 0 ? <LemonBadge.Number count={savedFilters.length} size="small" /> : null
                }
                onClick={() => setShowSavedFilters(!showSavedFilters)}
                active={showSavedFilters}
            >
                Saved filters
            </LemonButton>
            {appliedSavedFilter && (
                <LemonTag icon={<IconBookmark />} closable={false}>
                    {appliedSavedFilter.name}
                </LemonTag>
            )}
        </>
    )
}
