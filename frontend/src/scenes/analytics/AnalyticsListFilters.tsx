import { useActions, useValues } from 'kea'

import { IconTrends } from '@posthog/icons'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { membersLogic } from '~/models/membersLogic'
import { tagsModel } from '~/models/tagsModel'

import { AnalyticsDisplayMenu } from './AnalyticsDisplayMenu'
import { AnalyticsFilterOption, AnalyticsFilterPicker } from './AnalyticsFilterPicker'
import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsOwnerAvatar } from './AnalyticsOwner'
import { AnalyticsSearchInput } from './AnalyticsSearchInput'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, ANALYTICS_TYPES, AnalyticsTypeFilter } from './analyticsUtils'

function AnalyticsTypeOption({ type }: { type: AnalyticsTypeFilter }): JSX.Element {
    if (type === 'all') {
        return (
            <>
                <IconTrends />
                All types
            </>
        )
    }
    const info = ANALYTICS_TYPE_INFO[type]
    return (
        <>
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <span className="flex items-center" style={{ color: info.color }}>
                <AnalyticsTypeIcon type={type} />
            </span>
            {info.pluralLabel}
        </>
    )
}

/** Search, then the type, creator and tag pickers. */
export function AnalyticsListFilters(): JSX.Element {
    const { filters, filtersActive, searchInput, scope, insightsHidden } = useValues(analyticsListLogic)
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
            <Select
                value={filters.type}
                onValueChange={(value: AnalyticsTypeFilter | null) => value && setFilters({ type: value })}
            >
                <SelectTrigger size="sm" aria-label="Filter by type" data-attr="analytics-list-type-picker">
                    <SelectValue className="flex items-center gap-1">
                        {(value: AnalyticsTypeFilter) => <AnalyticsTypeOption type={value} />}
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value="all" data-attr="analytics-list-type-filter">
                        <AnalyticsTypeOption type="all" />
                    </SelectItem>
                    {ANALYTICS_TYPES.filter(
                        // A link can still open the insight type, so its option stays while it is the one shown.
                        (info) => !insightsHidden || info.type !== 'insight' || filters.type === 'insight'
                    ).map((info) => (
                        <SelectItem key={info.type} value={info.type} data-attr="analytics-list-type-filter">
                            <AnalyticsTypeOption type={info.type} />
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
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
            <div className="ml-auto">
                <AnalyticsDisplayMenu />
            </div>
        </div>
    )
}
