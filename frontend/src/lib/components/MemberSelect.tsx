import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonButtonProps, LemonDropdown, LemonDropdownProps, LemonInput } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

import { MemberSelectRow } from './MemberSelectRow'

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
    const { me, selectableMembers, meFirstMembers, search, membersLoading } = useValues(membersLogic)
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
        } else {
            setSearch('')
        }
    }, [showPopover]) // oxlint-disable-line react-hooks/exhaustive-deps

    const members = selectableMembers(excludedMembers, propToCompare)

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
                        {allowNone && (
                            <li>
                                <LemonButton fullWidth role="menuitem" size="small" onClick={() => _onChange(null)}>
                                    {defaultLabel}
                                </LemonButton>
                            </li>
                        )}

                        {members.map((member) => (
                            <MemberSelectRow
                                key={member.user.uuid}
                                member={member}
                                isYou={member.user.uuid === me?.user.uuid}
                                onClick={() => _onChange(member.user)}
                            />
                        ))}

                        {membersLoading ? (
                            <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                        ) : members.length === 0 ? (
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
                            {me?.user.uuid === selectedMemberAsUser.uuid ? ` (you)` : ''}
                        </span>
                    ) : (
                        defaultLabel
                    )}
                </LemonButton>
            )}
        </LemonDropdown>
    )
}
