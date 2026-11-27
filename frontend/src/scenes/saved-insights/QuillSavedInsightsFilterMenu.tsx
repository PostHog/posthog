import { useActions } from 'kea'
import posthog from 'posthog-js'

import { IconApps } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuContent,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
} from '@posthog/quill'

import { QuillTagsFilterSubMenu } from 'lib/components/QuillTagsFilterSubMenu'
import { AnalyticsCreatedBySubMenu } from 'scenes/analytics/AnalyticsCreatedBySubMenu'

import { membersLogic } from '~/models/membersLogic'

import { INSIGHT_TYPES_METADATA } from './insightTypesMetadata'
import { SavedInsightFilters } from './savedInsightsLogic'

const ALL_TYPES = 'All types'

const TYPE_OPTIONS: FilterOption[] = [
    { value: ALL_TYPES, label: ALL_TYPES, icon: <IconApps /> },
    ...Object.entries(INSIGHT_TYPES_METADATA)
        .filter(([, meta]) => meta.inMenu !== false)
        .map(([value, meta]) => ({ value, label: meta.name, icon: meta.icon ? <meta.icon /> : undefined })),
]

export function QuillSavedInsightsFilterMenu({
    filters,
    setFilters,
    active,
    onClear,
}: {
    filters: SavedInsightFilters
    setFilters: (filters: Partial<SavedInsightFilters>) => void
    active: boolean
    onClear: () => void
}): JSX.Element {
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const createdBy = filters.createdBy !== 'All users' ? filters.createdBy : []

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                if (open && createdBy.length > 0) {
                    ensureAllMembersLoaded()
                }
            }}
        >
            <FilterMenuTrigger active={active} dataAttr="saved-insights-modal-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterRadioSubMenu
                    label="Type"
                    options={TYPE_OPTIONS}
                    value={filters.insightType || ALL_TYPES}
                    defaultValue={ALL_TYPES}
                    onChange={(insightType) => {
                        setFilters({ insightType })
                        posthog.capture('saved insights filtered', { filter_type: 'insight_type', value: insightType })
                    }}
                    optionDataAttr="saved-insights-modal-type-filter"
                />
                <AnalyticsCreatedBySubMenu
                    selected={createdBy}
                    onChange={(userIds) => {
                        const createdByValue = userIds.length > 0 ? userIds : 'All users'
                        setFilters({ createdBy: createdByValue })
                        posthog.capture('saved insights filtered', { filter_type: 'created_by', value: createdByValue })
                    }}
                    dataAttr="saved-insights-modal-created-by"
                    optionDataAttr="saved-insights-modal-created-by-option"
                />
                <QuillTagsFilterSubMenu
                    logicKey="saved-insights-modal-tags"
                    selected={filters.tags ?? []}
                    onChange={(tags) => {
                        setFilters({ tags })
                        posthog.capture('saved insights filtered', { filter_type: 'tags', value: tags })
                    }}
                    dataAttr="saved-insights-modal-tags"
                    optionDataAttr="saved-insights-modal-tags-option"
                />
                <FilterClearItem active={active} onClear={onClear} dataAttr="saved-insights-modal-clear" />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
