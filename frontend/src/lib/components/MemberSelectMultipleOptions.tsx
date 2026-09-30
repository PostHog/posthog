import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { membersLogic } from 'scenes/organization/membersLogic'

import { OrganizationMemberType } from '~/types'

import { MemberSelectRow } from './MemberSelectRow'

export type MemberSelectMultipleOptionsProps = {
    /** Currently selected member user ids. */
    value: number[]
    onChange: (value: number[]) => void
    /** Member user ids to leave out of the list. */
    excludedMembers?: number[]
}

/**
 * Dropdown overlay of the multi-select member pickers: a search input, a "Clear selection" button,
 * and a scrollable checkbox list of organization members. Selected members also appear at the top
 * after selection activity stops.
 */
export function MemberSelectMultipleOptions({
    value,
    onChange,
    excludedMembers = [],
}: MemberSelectMultipleOptionsProps): JSX.Element {
    const { me, selectableMembers, membersLoading, search } = useValues(membersLogic)
    const { setSearch } = useActions(membersLogic)
    const [selectedIdsAtTop, setSelectedIdsAtTop] = useState(() => new Set(value))

    useEffect(() => {
        const timeout = setTimeout(() => setSelectedIdsAtTop(new Set(value)), 600)
        return () => clearTimeout(timeout)
    }, [value])

    const members = selectableMembers(excludedMembers, 'id')
    const selectedMembersAtTop = search ? [] : members.filter((member) => selectedIdsAtTop.has(member.user.id))

    const toggleMember = (userId: number): void => {
        const selected = new Set(value)
        if (selected.has(userId)) {
            selected.delete(userId)
        } else {
            selected.add(userId)
        }
        onChange(Array.from(selected))
    }

    const renderRow = (member: OrganizationMemberType, keyPrefix = ''): JSX.Element => (
        <MemberSelectRow
            key={`${keyPrefix}${member.user.uuid}`}
            member={member}
            isYou={member.user.uuid === me?.user.uuid}
            onClick={() => toggleMember(member.user.id)}
            checked={value.includes(member.user.id)}
        />
    )

    return (
        <div className="max-w-100 flex flex-col gap-2">
            <LemonInput type="search" placeholder="Search" autoFocus value={search} onChange={setSearch} fullWidth />
            <LemonButton
                data-attr="member-filter-clear-selection"
                fullWidth
                role="menuitem"
                size="small"
                type="tertiary"
                icon={<IconX />}
                disabledReason={value.length === 0 ? 'No members selected' : undefined}
                onClick={() => onChange([])}
            >
                Clear selection
            </LemonButton>
            <div className="max-h-80 overflow-y-auto flex flex-col gap-px">
                {selectedMembersAtTop.length > 0 && (
                    <ul className="flex flex-col gap-px" aria-label="Selected members">
                        {selectedMembersAtTop.map((member) => renderRow(member, 'selected-'))}
                        <li>
                            <LemonDivider className="my-1" />
                        </li>
                    </ul>
                )}
                <ul className="flex flex-col gap-px" aria-label="Members">
                    {members.map((member) => renderRow(member))}
                    {membersLoading ? (
                        <li className="p-2 text-secondary italic truncate border-t">Loading...</li>
                    ) : members.length === 0 ? (
                        <li className="p-2 text-secondary italic truncate border-t">
                            {search ? 'No matches' : 'No users'}
                        </li>
                    ) : null}
                </ul>
            </div>
        </div>
    )
}
