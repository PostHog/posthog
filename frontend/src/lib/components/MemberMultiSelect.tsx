import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonButtonProps, LemonDropdown, LemonDropdownProps, LemonInput } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

import { MemberSelectRow } from './MemberSelectRow'

export type MemberMultiSelectProps = {
    defaultLabel?: string
    // Array of user IDs (numbers)
    value: number[]
    excludedMembers?: number[]
    onChange: (value: number[]) => void
    children?: (selectedUsers: UserBasicType[]) => LemonDropdownProps['children']
}

export function MemberMultiSelect({
    defaultLabel = 'Any user',
    value,
    excludedMembers = [],
    onChange,
    children,
    ...buttonProps
}: MemberMultiSelectProps & Pick<LemonButtonProps, 'type' | 'size'>): JSX.Element {
    const { me, selectableMembers, meFirstMembers, search, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded, setSearch } = useActions(membersLogic)
    const [showPopover, setShowPopover] = useState(false)

    const selectedMembersAsUsers = useMemo(() => {
        if (!value || value.length === 0) {
            return []
        }
        return meFirstMembers.filter((member) => value.includes(member.user.id)).map((member) => member.user)
    }, [value, meFirstMembers])

    const _onChange = (newValues: number[]): void => {
        onChange(newValues)
    }

    const handleMemberToggle = (userId: number): void => {
        const selected = new Set(value || [])
        if (selected.has(userId)) {
            selected.delete(userId)
        } else {
            selected.add(userId)
        }
        _onChange(Array.from(selected))
    }

    const handleClear = (): void => {
        _onChange([])
        setShowPopover(false)
    }

    const handleVisibilityChange = (visible: boolean): void => {
        setShowPopover(visible)
        if (visible) {
            ensureAllMembersLoaded()
        }
    }

    // Load members when the selection is non-empty even before the popover opens, so a value
    // pre-populated from the URL resolves to a name rather than falling back to the default label.
    useEffect(() => {
        if (value?.length) {
            ensureAllMembersLoaded()
        }
    }, [value?.length]) // oxlint-disable-line react-hooks/exhaustive-deps

    const members = selectableMembers(excludedMembers, 'id')

    const selectedCount = value?.length || 0
    const buttonClass = selectedCount > 0 ? 'min-w-26' : 'w-26'

    const buttonLabel = ((): string => {
        if (selectedCount === 0) {
            return defaultLabel
        }
        if (selectedCount > 1) {
            return `${selectedCount} selected`
        }
        return selectedMembersAsUsers[0] ? fullName(selectedMembersAsUsers[0]) : defaultLabel
    })()

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            placement="bottom-start"
            actionable
            onVisibilityChange={handleVisibilityChange}
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
                                onClick={() => handleMemberToggle(member.user.id)}
                                checked={value?.includes(member.user.id) || false}
                            />
                        ))}

                        {membersLoading ? (
                            <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                        ) : members.length === 0 ? (
                            <div className="p-2 text-secondary italic truncate border-t">
                                {search ? <span>No matches</span> : <span>No users</span>}
                            </div>
                        ) : null}

                        {selectedCount > 0 && (
                            <>
                                <div className="my-1 border-t" />
                                <li>
                                    <LemonButton
                                        fullWidth
                                        role="menuitem"
                                        size="small"
                                        onClick={handleClear}
                                        type="secondary"
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
            {children ? (
                children(selectedMembersAsUsers)
            ) : (
                <LemonButton size="small" type="secondary" className={buttonClass} {...buttonProps}>
                    {buttonLabel}
                </LemonButton>
            )}
        </LemonDropdown>
    )
}
