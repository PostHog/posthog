import { useActions, useValues } from 'kea'

import { DropdownMenu, DropdownMenuContent, FilterClearItem, FilterMenuTrigger } from '@posthog/quill'

import { QuillTagsFilterSubMenu } from 'lib/components/QuillTagsFilterSubMenu'
import { AnalyticsCreatedBySubMenu } from 'scenes/analytics/AnalyticsCreatedBySubMenu'

import { membersLogic } from '~/models/membersLogic'

import { actionsLogic } from '../logics/actionsLogic'

export function QuillActionsFilterMenu(): JSX.Element {
    const { filters } = useValues(actionsLogic)
    const { setFilters } = useActions(actionsLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    const active = filters.createdBy.length > 0 || filters.tags.length > 0

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                if (open && filters.createdBy.length > 0) {
                    ensureAllMembersLoaded()
                }
            }}
        >
            <FilterMenuTrigger active={active} dataAttr="actions-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <AnalyticsCreatedBySubMenu
                    selected={filters.createdBy}
                    onChange={(createdBy) => setFilters({ createdBy })}
                    dataAttr="actions-filter-created-by"
                    optionDataAttr="actions-filter-created-by-option"
                />
                <QuillTagsFilterSubMenu
                    logicKey="actions-tags"
                    selected={filters.tags}
                    onChange={(tags) => setFilters({ tags })}
                    dataAttr="actions-filter-tags"
                    optionDataAttr="actions-filter-tags-option"
                />
                <FilterClearItem
                    active={active}
                    onClear={() => setFilters({ createdBy: [], tags: [] })}
                    dataAttr="actions-filter-clear"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
