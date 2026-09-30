import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { membersLogic } from 'scenes/organization/membersLogic'

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
 * and a scrollable checkbox list of organization members. Members selected when the dropdown opens
 * are listed first.
 */
export function MemberSelectMultipleOptions({
    value,
    onChange,
    excludedMembers = [],
}: MemberSelectMultipleOptionsProps): JSX.Element {
    const { me, selectableMembers, membersLoading, search } = useValues(membersLogic)
    const { setSearch } = useActions(membersLogic)
    // The popover mounts this overlay on open, so this is the selection at open time. Sorting by it
    // instead of `value` keeps a row from jumping to the top while the user toggles its checkbox.
    const [pinnedIds] = useState(() => new Set(value))

    const unsortedMembers = selectableMembers(excludedMembers, 'id')
    const members = [
        ...unsortedMembers.filter((member) => pinnedIds.has(member.user.id)),
        ...unsortedMembers.filter((member) => !pinnedIds.has(member.user.id)),
    ]

    const toggleMember = (userId: number): void => {
        const selected = new Set(value)
        if (selected.has(userId)) {
            selected.delete(userId)
        } else {
            selected.add(userId)
        }
        onChange(Array.from(selected))
    }

    return (
        <div className="max-w-100 flex flex-col gap-2">
            <LemonInput type="search" placeholder="Search" autoFocus value={search} onChange={setSearch} fullWidth />
            <LemonButton
                data-attr="member-filter-clear-selection"
                fullWidth
                role="menuitem"
                size="small"
                type="tertiary"
                disabledReason={value.length === 0 ? 'No members selected' : undefined}
                onClick={() => onChange([])}
            >
                Clear selection
            </LemonButton>
            <ul className="max-h-80 overflow-y-auto flex flex-col gap-px" aria-label="Members">
                {members.map((member) => (
                    <MemberSelectRow
                        key={member.user.uuid}
                        member={member}
                        isYou={member.user.uuid === me?.user.uuid}
                        onClick={() => toggleMember(member.user.id)}
                        checked={value.includes(member.user.id)}
                    />
                ))}
                {membersLoading ? (
                    <li className="p-2 text-secondary italic truncate border-t">Loading...</li>
                ) : members.length === 0 ? (
                    <li className="p-2 text-secondary italic truncate border-t">
                        {search ? 'No matches' : 'No users'}
                    </li>
                ) : null}
            </ul>
        </div>
    )
}
