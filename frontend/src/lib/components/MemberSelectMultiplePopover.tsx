import { useActions, useValues } from 'kea'

import { LemonDropdown, ProfilePicture } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

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
    const { me, otherMembers, membersLoading, search } = useValues(membersLogic)
    const { ensureAllMembersLoaded, setSearch } = useActions(membersLogic)

    const hasSelection = value.length > 0
    const currentUserId = me?.user.id
    const meToShow = me && !search.trim() ? me : null
    const isFilteredToCurrentUser = hasSelection && value.length === 1 && value[0] === currentUserId

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
                        {meToShow && (
                            <li>
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    icon={<ProfilePicture size="md" user={meToShow.user} />}
                                    onClick={() => toggleMember(meToShow.user.id)}
                                >
                                    <span className="flex items-center justify-between gap-2 flex-1">
                                        <span className="flex items-center gap-2 max-w-full">
                                            <input
                                                type="checkbox"
                                                className="cursor-pointer"
                                                checked={value.includes(meToShow.user.id)}
                                                readOnly
                                            />
                                            <span>{fullName(meToShow.user)}</span>
                                        </span>
                                        <span className="text-secondary">(you)</span>
                                    </span>
                                </LemonButton>
                            </li>
                        )}
                        {otherMembers.map((member) => (
                            <li key={member.user.uuid}>
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    icon={<ProfilePicture size="md" user={member.user} />}
                                    onClick={() => toggleMember(member.user.id)}
                                >
                                    <span className="flex items-center justify-between gap-2 flex-1">
                                        <span className="flex items-center gap-2 max-w-full">
                                            <input
                                                type="checkbox"
                                                className="cursor-pointer"
                                                checked={value.includes(member.user.id)}
                                                readOnly
                                            />
                                            <span>{fullName(member.user)}</span>
                                        </span>
                                    </span>
                                </LemonButton>
                            </li>
                        ))}
                        {membersLoading ? (
                            <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                        ) : !meToShow && otherMembers.length === 0 ? (
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
                {isFilteredToCurrentUser ? `${label} you` : hasSelection ? `${label} (${value.length})` : label}
            </LemonButton>
        </LemonDropdown>
    )
}
