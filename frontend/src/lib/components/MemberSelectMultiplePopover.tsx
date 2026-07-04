import { useActions, useValues } from 'kea'

import { LemonDropdown } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { membersLogic } from 'scenes/organization/membersLogic'

import { MemberSelectRow } from './MemberSelectRow'

export type MemberSelectMultiplePopoverProps = {
    /** Currently selected member user ids. */
    value: number[]
    onChange: (value: number[]) => void
    /** Trigger button label, also used in the "<label> you" / "<label> (N)" summaries. */
    label?: string
    /** When true, the trigger appears borderless (alt status) while nothing is selected. */
    borderless?: boolean
}

/**
 * Multi-select of organization members rendered as a labeled dropdown with a searchable,
 * checkbox member list. Shared by the dashboards and insights "Created by" filters.
 *
 * For a single-select member picker use `MemberSelect`; for a chip-style multi-select input
 * use `MemberSelectMultiple`.
 */
export function MemberSelectMultiplePopover({
    value,
    onChange,
    label = 'Created by',
    borderless = false,
}: MemberSelectMultiplePopoverProps): JSX.Element {
    const { me, selectableMembers, membersLoading, search } = useValues(membersLogic)
    const { ensureAllMembersLoaded, setSearch } = useActions(membersLogic)

    // Guard against callers handing us a non-array (e.g. a URL param parsed to a bare number).
    const selectedIds = Array.isArray(value) ? value : []
    const hasSelection = selectedIds.length > 0
    const currentUserId = me?.user.id
    const members = selectableMembers()
    const isFilteredToCurrentUser = hasSelection && selectedIds.length === 1 && selectedIds[0] === currentUserId

    const toggleMember = (userId: number): void => {
        const selected = new Set(selectedIds)
        if (selected.has(userId)) {
            selected.delete(userId)
        } else {
            selected.add(userId)
        }
        onChange(Array.from(selected))
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            matchWidth={false}
            placement="bottom-end"
            actionable
            onVisibilityChange={(visible) => {
                if (visible) {
                    ensureAllMembersLoaded()
                    setSearch('')
                }
            }}
            overlay={
                <div className="max-w-100 deprecated-space-y-2">
                    <LemonInput
                        type="search"
                        placeholder="Search"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                    <ul className="deprecated-space-y-px">
                        {members.map((member) => (
                            <MemberSelectRow
                                key={member.user.uuid}
                                member={member}
                                isYou={member.user.uuid === me?.user.uuid}
                                onClick={() => toggleMember(member.user.id)}
                                checked={selectedIds.includes(member.user.id)}
                            />
                        ))}
                        {membersLoading ? (
                            <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                        ) : members.length === 0 ? (
                            <div className="p-2 text-secondary italic truncate border-t">
                                {search ? <span>No matches</span> : <span>No users</span>}
                            </div>
                        ) : null}
                        {hasSelection && (
                            <>
                                <div className="my-1 border-t" />
                                <li>
                                    <LemonButton
                                        fullWidth
                                        role="menuitem"
                                        size="small"
                                        onClick={() => onChange([])}
                                        type="tertiary"
                                    >
                                        Clear selection
                                    </LemonButton>
                                </li>
                            </>
                        )}
                    </ul>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                status={borderless && !hasSelection ? 'alt' : 'default'}
                active={hasSelection}
            >
                {isFilteredToCurrentUser ? `${label} you` : hasSelection ? `${label} (${selectedIds.length})` : label}
            </LemonButton>
        </LemonDropdown>
    )
}
