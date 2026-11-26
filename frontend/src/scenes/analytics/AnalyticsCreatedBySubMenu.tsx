import { useActions, useValues } from 'kea'

import { FilterSearchSubMenu } from '@posthog/quill'

import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { membersLogic } from '~/models/membersLogic'

import { AnalyticsOwnerAvatar } from './AnalyticsOwner'

/** The "Created by" submenu of a list's filter menu, picking organization members by user id. */
export function AnalyticsCreatedBySubMenu({
    selected,
    onChange,
    dataAttr,
    optionDataAttr,
}: {
    selected: number[]
    onChange: (userIds: number[]) => void
    dataAttr: string
    optionDataAttr: string
}): JSX.Element {
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)

    return (
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
            selected={selected.map(String)}
            onChange={(ids) => onChange(ids.map(Number))}
            loading={membersLoading}
            searchPlaceholder="Search people"
            emptyText="No one matches"
            onOpen={ensureAllMembersLoaded}
            dataAttr={dataAttr}
            optionDataAttr={optionDataAttr}
        />
    )
}
