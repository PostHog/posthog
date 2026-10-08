import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonButtonProps, LemonDropdown, LemonDropdownProps } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

import { MemberSelectMultipleOptions } from './MemberSelectMultipleOptions'
import { useMemberFilterClearAction } from './useMemberFilterClearAction'

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
    excludedMembers,
    onChange,
    children,
    ...buttonProps
}: MemberMultiSelectProps & Pick<LemonButtonProps, 'type' | 'size'>): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
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

    const handleVisibilityChange = (visible: boolean): void => {
        setShowPopover(visible)
        if (visible) {
            ensureAllMembersLoaded()
            setSearch('')
        }
    }

    // Load members when the selection is non-empty even before the popover opens, so a value
    // pre-populated from the URL resolves to a name rather than falling back to the default label.
    useEffect(() => {
        if (value?.length) {
            ensureAllMembersLoaded()
        }
    }, [value?.length]) // oxlint-disable-line react-hooks/exhaustive-deps

    const selectedCount = value?.length || 0
    const buttonClass = selectedCount > 0 ? 'min-w-26' : 'w-26'
    const { triggerRef, sideAction } = useMemberFilterClearAction(selectedCount > 0, () => _onChange([]))

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
            overflowHidden
            onVisibilityChange={handleVisibilityChange}
            overlay={
                <MemberSelectMultipleOptions
                    value={value || []}
                    onChange={_onChange}
                    excludedMembers={excludedMembers}
                />
            }
        >
            {children ? (
                children(selectedMembersAsUsers)
            ) : (
                <LemonButton
                    ref={triggerRef}
                    size="small"
                    type="secondary"
                    className={buttonClass}
                    sideAction={sideAction}
                    {...buttonProps}
                >
                    {buttonLabel}
                </LemonButton>
            )}
        </LemonDropdown>
    )
}
