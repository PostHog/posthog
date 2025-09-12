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

export type MemberSelectProps = {
    defaultLabel?: string
    allowNone?: boolean
    // NOTE: Trying to cover a lot of different cases - if string we assume uuid, if number we assume id
    value: string | number | null
    excludedMembers?: (string | number)[]
    onChange: (value: UserBasicType | null) => void
    children?: (selectedUser: UserBasicType | null) => LemonDropdownProps['children']
}

export function MemberSelect({
    defaultLabel = 'Any user',
    allowNone = true,
    value,
    excludedMembers = [],
    onChange,
    children,
    ...buttonProps
}: MemberSelectProps & Pick<LemonButtonProps, 'type' | 'size'>): JSX.Element {
    const { meFirstMembers, filteredMembers, search, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded, setSearch } = useActions(membersLogic)
    const [showPopover, setShowPopover] = useState(false)

    const propToCompare = typeof value === 'string' ? 'uuid' : 'id'

    const selectedMemberAsUser = useMemo(() => {
        if (!value) {
            return null
        }
        return meFirstMembers.find((member) => member.user[propToCompare] === value)?.user ?? null
    }, [value, meFirstMembers, propToCompare])

    const _onChange = (value: UserBasicType | null): void => {
        setShowPopover(false)
        onChange(value)
    }

    useEffect(() => {
        if (showPopover) {
            ensureAllMembersLoaded()
        }
    }, [showPopover]) // oxlint-disable-line react-hooks/exhaustive-deps

    const selectableMembers = filteredMembers.filter((m) => !excludedMembers.includes(m.user[propToCompare]))

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            actionable
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={
                <div className="max-w-100 deprecated-space-y-2 overflow-hidden">
                    <LemonInput
                        type="search"
                        placeholder="Search"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                    <ul className="deprecated-space-y-px">
                        {allowNone && (
                            <li>
                                <LemonButton fullWidth role="menuitem" size="small" onClick={() => _onChange(null)}>
                                    {defaultLabel}
                                </LemonButton>
                            </li>
                        )}

                        {selectableMembers.map((member) => (
                            <li key={member.user.uuid}>
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    icon={<ProfilePicture size="md" user={member.user} />}
                                    onClick={() => _onChange(member.user)}
                                >
                                    <span className="flex items-center justify-between gap-2 flex-1">
                                        <span>{fullName(member.user)}</span>
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
                    </ul>
                </div>
            }
        >
            {children ? (
                children(selectedMemberAsUser)
            ) : (
                <LemonButton size="small" type="secondary" {...buttonProps}>
                    {selectedMemberAsUser ? (
                        <span>
                            {fullName(selectedMemberAsUser)}
                            {meFirstMembers[0].user.uuid === selectedMemberAsUser.uuid ? ` (you)` : ''}
                        </span>
                    ) : (
                        defaultLabel
                    )}
                </LemonButton>
            )}
        </LemonDropdown>
    )
}
