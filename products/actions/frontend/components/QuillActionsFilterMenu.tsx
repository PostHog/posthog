import { useActions, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuContent,
    FilterClearItem,
    FilterMenuTrigger,
    FilterSearchSubMenu,
} from '@posthog/quill'

import { QuillTagsFilterSubMenu } from 'lib/components/QuillTagsFilterSubMenu'
import { fullName } from 'lib/utils/strings'
import { AnalyticsOwnerAvatar } from 'scenes/analytics/AnalyticsOwner'
import { userLogic } from 'scenes/userLogic'

import { membersLogic } from '~/models/membersLogic'

import { actionsLogic } from '../logics/actionsLogic'

export function QuillActionsFilterMenu(): JSX.Element {
    const { filters } = useValues(actionsLogic)
    const { setFilters } = useActions(actionsLogic)
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)

    const createdBy = filters.createdBy.map(String)
    const active = filters.createdBy.length > 0 || filters.tags.length > 0

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                if (open && createdBy.length > 0) {
                    ensureAllMembersLoaded()
                }
            }}
        >
            <FilterMenuTrigger active={active} dataAttr="actions-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
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
                    onChange={(ids) => setFilters({ createdBy: ids.map(Number) })}
                    loading={membersLoading}
                    searchPlaceholder="Search people"
                    emptyText="No one matches"
                    onOpen={ensureAllMembersLoaded}
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
