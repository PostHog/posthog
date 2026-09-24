import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonButton, LemonButtonProps, LemonDropdown, LemonDropdownProps, LemonInput } from '@posthog/lemon-ui'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

import { MemberSelectRow } from './MemberSelectRow'

export type MemberSelectProps = {
    defaultLabel?: string
    allowNone?: boolean
    extraOptions?: { label: string; onClick: () => void }[]
    options?: { uuid: string; name: string; email: string; trailing?: string | number }[]
    optionsLoading?: boolean
    onSearch?: (query: string) => void
    onSelectOption?: (uuid: string, name: string) => void
    // NOTE: Trying to cover a lot of different cases - if string we assume uuid, if number we assume id
    value: string | number | null
    excludedMembers?: (string | number)[]
    onChange: (value: UserBasicType | null) => void
    children?: (selectedUser: UserBasicType | null) => LemonDropdownProps['children']
}

export function MemberSelect({
    defaultLabel = 'Any user',
    allowNone = true,
    extraOptions = [],
    options,
    optionsLoading,
    onSearch,
    onSelectOption,
    value,
    excludedMembers = [],
    onChange,
    children,
    ...buttonProps
}: MemberSelectProps & Pick<LemonButtonProps, 'type' | 'size'>): JSX.Element {
    const { me, selectableMembers, meFirstMembers, search, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded, setSearch } = useActions(membersLogic)
    const [showPopover, setShowPopover] = useState(false)
    const [optionSearch, setOptionSearch] = useState('')
    const searchValue = options ? optionSearch : search

    const changeSearch = (query: string): void => {
        if (options) {
            setOptionSearch(query)
            onSearch?.(query)
        } else {
            setSearch(query)
        }
    }

    const propToCompare = typeof value === 'string' ? 'uuid' : 'id'

    const selectedMemberAsUser = useMemo(() => {
        if (!value) {
            return null
        }
        return meFirstMembers.find((member) => member.user[propToCompare] === value)?.user ?? null
    }, [value, meFirstMembers, propToCompare])

    const handleVisibilityChange = (visible: boolean): void => {
        setShowPopover(visible)
        if (searchValue) {
            changeSearch('')
        }
        if (visible && !options) {
            ensureAllMembersLoaded()
        }
    }

    const _onChange = (value: UserBasicType | null): void => {
        handleVisibilityChange(false)
        onChange(value)
    }

    const members = showPopover && !options ? selectableMembers(excludedMembers, propToCompare) : []
    const displayedOptions =
        options && !optionSearch && me
            ? [...options].sort(
                  (first, second) => Number(second.uuid === me.user.uuid) - Number(first.uuid === me.user.uuid)
              )
            : options

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            placement="bottom-start"
            actionable
            onVisibilityChange={handleVisibilityChange}
            overlay={
                showPopover ? (
                    <div className="max-w-100 deprecated-space-y-2">
                        <LemonInput
                            type="search"
                            placeholder="Search"
                            autoFocus
                            value={searchValue}
                            onChange={changeSearch}
                            fullWidth
                        />
                        <ul className="deprecated-space-y-px">
                            {extraOptions.map((option) => (
                                <li key={option.label}>
                                    <LemonButton
                                        fullWidth
                                        role="menuitem"
                                        size="small"
                                        onClick={() => {
                                            handleVisibilityChange(false)
                                            option.onClick()
                                        }}
                                    >
                                        {option.label}
                                    </LemonButton>
                                </li>
                            ))}
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

                            {displayedOptions?.map((option) => (
                                <li key={option.uuid}>
                                    <LemonButton
                                        fullWidth
                                        role="menuitem"
                                        size="small"
                                        icon={
                                            <ProfilePicture
                                                size="md"
                                                user={{ first_name: option.name, email: option.email }}
                                            />
                                        }
                                        onClick={() => {
                                            handleVisibilityChange(false)
                                            onSelectOption?.(option.uuid, option.name || option.email)
                                        }}
                                    >
                                        <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
                                            <span className="min-w-0 flex-1 truncate">
                                                {option.name || option.email}
                                            </span>
                                            <span className="shrink-0 text-secondary">{option.trailing}</span>
                                        </span>
                                    </LemonButton>
                                </li>
                            ))}

                            {(options ? optionsLoading : membersLoading) ? (
                                <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                            ) : (options ?? members).length === 0 ? (
                                <div className="p-2 text-secondary italic truncate border-t">
                                    {searchValue ? <span>No matches</span> : <span>No users</span>}
                                </div>
                            ) : null}
                        </ul>
                    </div>
                ) : null
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
