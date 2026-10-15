import { useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { membersLogic } from 'scenes/organization/membersLogic'

import { MemberSelectRow } from './MemberSelectRow'

const NO_EXCLUDED_MEMBERS: number[] = []

export type MemberSelectMultipleOptionsProps = {
    /** Currently selected member user ids. */
    value: number[]
    onChange: (value: number[]) => void
    /** Member user ids to leave out of the list. */
    excludedMembers?: number[]
}

export function MemberSelectMultipleOptions({
    value,
    onChange,
    excludedMembers = NO_EXCLUDED_MEMBERS,
}: MemberSelectMultipleOptionsProps): JSX.Element {
    const { me, selectableMembers, membersLoading, search } = useValues(membersLogic)
    const { setSearch } = useActions(membersLogic)
    const searchInputRef = useRef<HTMLInputElement>(null)
    // The dropdown unmounts this list when it closes, so each open takes a new snapshot of the selection.
    const [selectedAtOpen] = useState(() => new Set(value))
    const members = useMemo(
        () =>
            [...selectableMembers(excludedMembers, 'id')].sort(
                (first, second) =>
                    Number(selectedAtOpen.has(second.user.id)) - Number(selectedAtOpen.has(first.user.id))
            ),
        [selectableMembers, excludedMembers, selectedAtOpen]
    )

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
        <div className="max-w-100 min-h-0 flex flex-col gap-2 p-1">
            <LemonInput
                type="search"
                placeholder="Search"
                autoFocus
                value={search}
                onChange={setSearch}
                inputRef={searchInputRef}
                fullWidth
            />
            <LemonButton
                data-attr="member-filter-clear-selection"
                fullWidth
                role="menuitem"
                size="small"
                type="tertiary"
                icon={<IconX />}
                disabledReason={value.length === 0 ? 'No members selected' : undefined}
                onClick={() => {
                    onChange([])
                    // The disabled button renders inside a tooltip, so React replaces the focused node.
                    // Move the focus to the search box so that keyboard users can pick new members.
                    searchInputRef.current?.focus()
                }}
            >
                Clear selection
            </LemonButton>
            <div className="max-h-80 min-h-0 overflow-y-auto">
                <ul className="flex flex-col gap-px" aria-label="Members">
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
        </div>
    )
}
