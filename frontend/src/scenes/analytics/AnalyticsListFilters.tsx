import { useActions, useValues } from 'kea'

import { IconTrends } from '@posthog/icons'
import { Button, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { tagsModel } from '~/models/tagsModel'

import { AnalyticsFilterOption, AnalyticsFilterPicker } from './AnalyticsFilterPicker'
import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsOwnerAvatar } from './AnalyticsOwner'
import { AnalyticsSearchInput } from './AnalyticsSearchInput'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPES, AnalyticsTypeFilter } from './analyticsUtils'

/** Search, type, creator and the personal toggle, all one height so the row reads as one bar. */
export function AnalyticsListFilters(): JSX.Element {
    const { filters, filtersActive, searchInput, scope } = useValues(analyticsListLogic)
    const { setSearchInput, setFilters, clearFilters } = useActions(analyticsListLogic)
    const { tags: allTags, tagsLoading } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)
    const memberOptions: AnalyticsFilterOption[] = meFirstMembers.map((member) => ({
        value: member.user.uuid,
        label: fullName(member.user) || member.user.email,
        media: <AnalyticsOwnerAvatar owner={member.user} />,
        hint: member.user.uuid === user?.uuid ? '(you)' : undefined,
    }))

    return (
        <div className="flex flex-wrap items-center gap-2">
            <AnalyticsSearchInput
                value={searchInput}
                onChange={setSearchInput}
                label="Search analytics"
                placeholder="Search"
                dataAttr="analytics-list-search"
            />
            <ToggleGroup
                size="lg"
                variant="default"
                aria-label="Filter by type"
                className="h-8"
                value={[filters.type]}
                onValueChange={(value: string[]) => value[0] && setFilters({ type: value[0] as AnalyticsTypeFilter })}
            >
                <ToggleGroupItem value="all" size="lg" data-attr="analytics-list-type-filter">
                    <IconTrends />
                    All
                </ToggleGroupItem>
                {ANALYTICS_TYPES.map((info) => (
                    <ToggleGroupItem
                        key={info.type}
                        value={info.type}
                        size="lg"
                        aria-label={info.pluralLabel}
                        title={info.pluralLabel}
                        data-attr="analytics-list-type-filter"
                    >
                        <span
                            className="flex items-center [&_svg]:size-4"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ color: info.color }}
                        >
                            <AnalyticsTypeIcon type={info.type} />
                        </span>
                        <span className="hidden @6xl/analytics:inline">{info.pluralLabel}</span>
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            {scope === 'all' && (
                <AnalyticsFilterPicker
                    label="Created by"
                    value={filters.createdBy}
                    onChange={(createdBy) => setFilters({ createdBy })}
                    onOpen={ensureAllMembersLoaded}
                    loading={membersLoading}
                    options={memberOptions}
                    searchPlaceholder="Search people"
                    emptyText="No one matches"
                    dataAttr="analytics-list-created-by"
                />
            )}
            <AnalyticsFilterPicker
                label="Tags"
                value={filters.tags}
                onChange={(tags) => setFilters({ tags })}
                onOpen={loadTagsIfNeeded}
                loading={tagsLoading}
                options={allTags.map((tag) => ({ value: tag, label: tag }))}
                searchPlaceholder="Search tags"
                emptyText="No tag matches"
                dataAttr="analytics-list-tags"
            />
            {filtersActive && (
                <Button variant="link-muted" size="sm" onClick={() => clearFilters()} data-attr="analytics-list-clear">
                    Clear filters
                </Button>
            )}
        </div>
    )
}
