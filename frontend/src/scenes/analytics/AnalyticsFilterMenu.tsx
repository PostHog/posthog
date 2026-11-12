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
    FilterMenuOpenTiming,
    FilterMenuTrigger,
    FilterOption,
    FilterSearchSubMenu,
} from '@posthog/quill'

import { useTagPages } from 'lib/components/useTagPages'
import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { membersLogic } from '~/models/membersLogic'

import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsOwnerAvatar } from './AnalyticsOwner'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPES, AnalyticsType } from './analyticsUtils'

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

function captureFilterMenuOpened(
    menu: 'analytics-tags' | 'analytics-created-by',
    { durationMs, optionCount }: FilterMenuOpenTiming
): void {
    posthog.capture('filter menu opened', {
        menu,
        duration_ms: Math.round(durationMs),
        option_count: optionCount,
    })
}

/**
 * The list's filters in one menu, laid out like the nav rail's: a row per filter, then display choices, then Clear
 * filters. The display choices are saved on the person, so they never count as a filter.
 */
export function AnalyticsFilterMenu(): JSX.Element {
    const { filters, scope, insightsHidden, narrowingFiltersActive } = useValues(analyticsListLogic)
    const { setFilters, setInsightsHidden, clearNarrowingFilters } = useActions(analyticsListLogic)
    const tagPages = useTagPages('analytics-list-tags')
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)

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
                        onOpened={(timing) => captureFilterMenuOpened('analytics-created-by', timing)}
                        dataAttr="analytics-list-created-by"
                        optionDataAttr="analytics-list-created-by-option"
                    />
                )}
                <FilterSearchSubMenu
                    label="Tags"
                    allLabel="Any tag"
                    pluralNoun="tags"
                    options={tagPages.tags.map(({ tag }) => ({ value: tag, label: tag }))}
                    selected={filters.tags}
                    onChange={(tags) => setFilters({ tags })}
                    loading={tagPages.awaitingFirstPage || tagPages.pageLoading}
                    searchPlaceholder="Search tags"
                    emptyText="No matching tags"
                    onOpen={() => tagPages.setOpen(true)}
                    onClose={() => tagPages.setOpen(false)}
                    onSearchChange={tagPages.setSearch}
                    onScrollEnd={tagPages.loadMore}
                    error={tagPages.error ? "Couldn't load tags." : undefined}
                    onRetry={tagPages.retry}
                    onOpened={(timing) => captureFilterMenuOpened('analytics-tags', timing)}
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
