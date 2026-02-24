import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import {
    LemonButton,
    LemonButtonProps,
    LemonDropdown,
    LemonDropdownProps,
    LemonInput,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { fullName } from 'lib/utils'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

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
    const { meFirstMembers, filteredMembers, search, membersLoading } = useValues(membersLogic)
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

    useEffect(() => {
        if (showPopover) {
            ensureAllMembersLoaded()
        }
    }, [showPopover]) // oxlint-disable-line react-hooks/exhaustive-deps

    const selectableMembers = filteredMembers.filter((m) => !excludedMembers.includes(m.user.id))

    const selectedCount = value?.length || 0
    const buttonClass = selectedCount > 0 ? 'min-w-26' : 'w-26'

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            placement="bottom-start"
            actionable
            onVisibilityChange={(visible) => setShowPopover(visible)}
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
                        {selectableMembers.map((member) => (
                            <li key={member.user.uuid}>
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    icon={<ProfilePicture size="md" user={member.user} />}
                                    onClick={() => handleMemberToggle(member.user.id)}
                                >
                                    <span className="flex items-center justify-between gap-2 flex-1">
                                        <span className="flex items-center gap-2 max-w-full">
                                            <input
                                                type="checkbox"
                                                className="cursor-pointer"
                                                checked={value?.includes(member.user.id) || false}
                                                readOnly
                                            />
                                            <span>{fullName(member.user)}</span>
                                        </span>
                                        <span className="text-secondary">
                                            {meFirstMembers[0] === member && `(you)`}
                                        </span>
                                    </span>
                                </LemonButton>
                            </li>
                        ))}

                        {membersLoading ? (
                            <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                        ) : selectableMembers.length === 0 ? (
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
                    {selectedCount > 0 ? `${selectedCount} selected` : defaultLabel}
                </LemonButton>
            )}
        </LemonDropdown>
    )
}
