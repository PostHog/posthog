import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

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

import { AnalyticsOrderBy } from './analyticsFeed'
import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsOwnerAvatar } from './AnalyticsOwner'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPES, AnalyticsType } from './analyticsUtils'

type AnalyticsSort = NonNullable<AnalyticsListDisplayConfiguration['default_sort']>

const SORT_OPTIONS: FilterOption<AnalyticsOrderBy>[] = [
    { value: '-last_viewed_at', label: 'Last viewed' },
    { value: '-created_at', label: 'Created' },
]

// Only a header click or a link reaches these orders, so each shows as a row only while it is in force.
const OLDEST_FIRST_OPTIONS: Partial<Record<AnalyticsOrderBy, FilterOption<AnalyticsOrderBy>>> = {
    last_viewed_at: { value: 'last_viewed_at', label: 'Last viewed, oldest first' },
    created_at: { value: 'created_at', label: 'Created, oldest first' },
}

function isAnalyticsSort(orderBy: AnalyticsOrderBy): orderBy is AnalyticsSort {
    return orderBy === '-last_viewed_at' || orderBy === '-created_at'
}

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

function captureFilterMenuOpened(menu: string, durationMs: number, optionCount: number): void {
    posthog.capture('filter menu opened', {
        menu,
        duration_ms: Math.round(durationMs),
        option_count: optionCount,
    })
}

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
    const sort = filters.orderBy ?? defaultSort
    const oldestFirstOption = OLDEST_FIRST_OPTIONS[sort]

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                // The Created by row names the people picked, so it needs them as soon as the menu shows.
                if (open && scope === 'all' && filters.createdBy.length > 0) {
                    ensureAllMembersLoaded()
                }
            }}
        >
            <FilterMenuTrigger active={narrowingFiltersActive} dataAttr="analytics-list-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterRadioSubMenu
                    label="Sort by"
                    options={oldestFirstOption ? [...SORT_OPTIONS, oldestFirstOption] : SORT_OPTIONS}
                    value={sort}
                    onChange={(next) => {
                        if (isAnalyticsSort(next)) {
                            setDefaultSort(next)
                        }
                    }}
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
                        onOpen={ensureAllMembersLoaded}
                        onOpened={(durationMs) =>
                            captureFilterMenuOpened('analytics-created-by', durationMs, meFirstMembers.length)
                        }
                        dataAttr="analytics-list-created-by"
                        optionDataAttr="analytics-list-created-by-option"
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
                    onOpen={loadTagsIfNeeded}
                    onOpened={(durationMs) => captureFilterMenuOpened('analytics-tags', durationMs, allTags.length)}
                    dataAttr="analytics-list-tags"
                    optionDataAttr="analytics-list-tags-option"
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
