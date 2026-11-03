import { useActions, useValues } from 'kea'

import { IconTrends } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuSeparator,
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
    FilterSearchSubMenu,
} from '@posthog/quill'

import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { membersLogic } from '~/models/membersLogic'
import { tagsModel } from '~/models/tagsModel'
import { AnalyticsListDisplayConfiguration } from '~/queries/schema/schema-general'

import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsOwnerAvatar } from './AnalyticsOwner'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPES, AnalyticsType } from './analyticsUtils'

type AnalyticsSort = NonNullable<AnalyticsListDisplayConfiguration['default_sort']>

const SORT_OPTIONS: FilterOption<AnalyticsSort>[] = [
    { value: '-last_viewed_at', label: 'Last viewed' },
    { value: '-created_at', label: 'Created' },
]

const TYPE_OPTIONS: FilterOption<AnalyticsType>[] = ANALYTICS_TYPES.map((info) => ({
    value: info.type,
    label: info.pluralLabel,
    icon: (
        // eslint-disable-next-line react/forbid-dom-props
        <span className="flex items-center" style={{ color: info.color }}>
            <AnalyticsTypeIcon type={info.type} />
        </span>
    ),
}))

/**
 * The list's controls in one menu, laid out like the nav rail's: sort, then a row per filter, then display choices, then
 * Clear filters. The sort and display choices are saved on the person, so they never count as a filter.
 */
export function AnalyticsFilterMenu(): JSX.Element {
    const { filters, scope, insightsHidden, defaultSort, narrowingFiltersActive } = useValues(analyticsListLogic)
    const { setFilters, setInsightsHidden, setDefaultSort, clearNarrowingFilters } = useActions(analyticsListLogic)
    const { tags: allTags, tagsLoading } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                if (open) {
                    ensureAllMembersLoaded()
                    loadTagsIfNeeded()
                }
            }}
        >
            <FilterMenuTrigger active={narrowingFiltersActive} dataAttr="analytics-list-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterRadioSubMenu
                    label="Sort by"
                    options={SORT_OPTIONS}
                    value={defaultSort}
                    onChange={setDefaultSort}
                    optionDataAttr="analytics-list-default-sort"
                />
                <DropdownMenuSeparator />
                <FilterCheckboxSubMenu
                    label="Type"
                    allLabel="All types"
                    allIcon={<IconTrends />}
                    pluralNoun="types"
                    // A link can still open the insight type, so its option stays while it is picked.
                    options={TYPE_OPTIONS.filter(
                        ({ value }) => !insightsHidden || value !== 'insight' || filters.types.includes('insight')
                    )}
                    selected={filters.types}
                    onChange={(types) => setFilters({ types })}
                    dataAttr="analytics-list-type-picker"
                    optionDataAttr="analytics-list-type-filter"
                />
                {scope === 'all' && (
                    <FilterSearchSubMenu
                        label="Created by"
                        allLabel="Any user"
                        pluralNoun="people"
                        options={meFirstMembers.map((member) => ({
                            value: member.user.uuid,
                            label: fullName(member.user) || member.user.email,
                            icon: <AnalyticsOwnerAvatar owner={member.user} />,
                            hint: member.user.uuid === user?.uuid ? '(you)' : undefined,
                        }))}
                        selected={filters.createdBy}
                        onChange={(createdBy) => setFilters({ createdBy })}
                        loading={membersLoading}
                        searchPlaceholder="Search people"
                        emptyText="No one matches"
                        dataAttr="analytics-list-created-by"
                    />
                )}
                <FilterSearchSubMenu
                    label="Tags"
                    allLabel="Any tag"
                    pluralNoun="tags"
                    options={allTags.map((tag) => ({ value: tag, label: tag }))}
                    selected={filters.tags}
                    onChange={(tags) => setFilters({ tags })}
                    loading={tagsLoading}
                    searchPlaceholder="Search tags"
                    emptyText="No tag matches"
                    dataAttr="analytics-list-tags"
                />
                <DropdownMenuSeparator />
                <DropdownMenuCheckboxItem
                    checked={insightsHidden}
                    closeOnClick={false}
                    onCheckedChange={(checked) => setInsightsHidden(checked)}
                    data-attr="analytics-list-hide-insights"
                >
                    Hide insights
                </DropdownMenuCheckboxItem>
                <FilterClearItem
                    active={narrowingFiltersActive}
                    onClear={clearNarrowingFilters}
                    dataAttr="analytics-list-clear"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
