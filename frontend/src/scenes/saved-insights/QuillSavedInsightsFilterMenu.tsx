import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconApps } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuContent,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
    FilterSearchSubMenu,
} from '@posthog/quill'

import { useTagPages } from 'lib/components/useTagPages'
import { fullName } from 'lib/utils/strings'
import { AnalyticsOwnerAvatar } from 'scenes/analytics/AnalyticsOwner'
import { userLogic } from 'scenes/userLogic'

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
    const tagPages = useTagPages('saved-insights-modal-tags')
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)
    const createdBy = filters.createdBy !== 'All users' ? filters.createdBy.map(String) : []

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
                <FilterSearchSubMenu
                    label="Created by"
                    allLabel="Any user"
                    pluralNoun="people"
                    options={meFirstMembers.map((member) => ({
                        value: String(member.user.id),
                        label: fullName(member.user) || member.user.email,
                        icon: <AnalyticsOwnerAvatar owner={member.user} />,
                        hint: member.user.uuid === user?.uuid ? '(you)' : undefined,
                    }))}
                    selected={createdBy}
                    onChange={(ids) => {
                        const createdByValue = ids.length > 0 ? ids.map(Number) : 'All users'
                        setFilters({ createdBy: createdByValue })
                        posthog.capture('saved insights filtered', { filter_type: 'created_by', value: createdByValue })
                    }}
                    loading={membersLoading}
                    searchPlaceholder="Search people"
                    emptyText="No one matches"
                    onOpen={ensureAllMembersLoaded}
                    dataAttr="saved-insights-modal-created-by"
                    optionDataAttr="saved-insights-modal-created-by-option"
                />
                <FilterSearchSubMenu
                    label="Tags"
                    allLabel="Any tag"
                    pluralNoun="tags"
                    options={tagPages.tags.map(({ tag }) => ({ value: tag, label: tag }))}
                    selected={filters.tags ?? []}
                    onChange={(tags) => {
                        setFilters({ tags })
                        posthog.capture('saved insights filtered', { filter_type: 'tags', value: tags })
                    }}
                    loading={tagPages.awaitingFirstPage || tagPages.pageLoading}
                    searchPlaceholder="Search tags"
                    emptyText="No matching tags"
                    onOpen={() => tagPages.setOpen(true)}
                    onClose={() => tagPages.setOpen(false)}
                    onSearchChange={tagPages.setSearch}
                    onScrollEnd={tagPages.loadMore}
                    error={tagPages.error ? "Couldn't load tags." : undefined}
                    onRetry={tagPages.retry}
                    dataAttr="saved-insights-modal-tags"
                    optionDataAttr="saved-insights-modal-tags-option"
                />
                <FilterClearItem active={active} onClear={onClear} dataAttr="saved-insights-modal-clear" />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
