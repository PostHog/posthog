import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonButton, LemonButtonProps, LemonDropdown, LemonDropdownProps, LemonInput } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

import { MemberSelectOptions } from './MemberSelectOptions'

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
        if (searchValue && !options) {
            changeSearch('')
        }
        if (visible && !options) {
            ensureAllMembersLoaded()
        }
    }

    const closeAfterSelection = (): void => {
        if (options && searchValue) {
            changeSearch('')
        }
        handleVisibilityChange(false)
    }

    const _onChange = (value: UserBasicType | null): void => {
        closeAfterSelection()
        onChange(value)
    }

    const members = showPopover && !options ? selectableMembers(excludedMembers, propToCompare) : []
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
                        <MemberSelectOptions
                            extraOptions={extraOptions}
                            allowNone={allowNone}
                            defaultLabel={defaultLabel}
                            members={members}
                            currentUserUuid={me?.user.uuid}
                            options={options}
                            optionsLoading={optionsLoading}
                            membersLoading={membersLoading}
                            searchValue={searchValue}
                            onChange={_onChange}
                            onSelectOption={onSelectOption}
                            onClose={closeAfterSelection}
                        />
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
