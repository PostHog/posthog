import { LemonButton, LemonButtonProps, LemonDropdown, LemonInput, ProfilePicture } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { fullName } from 'lib/utils'
import { useMemo, useState } from 'react'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

export type MemberSelectProps = Pick<LemonButtonProps, 'size' | 'type'> & {
    defaultLabel?: string
    // NOTE: Trying to cover a lot of different cases - if string we assume uuid, if number we assume id
    value: UserBasicType | string | number | null
    onChange: (value: UserBasicType | null) => void
}

export function MemberSelect({
    defaultLabel = 'All users',
    value,
    onChange,
    ...buttonProps
}: MemberSelectProps): JSX.Element {
    const { meFirstMembers, membersFuse } = useValues(membersLogic)
    const [showPopover, setShowPopover] = useState(false)
    const [searchTerm, setSearchTerm] = useState('')

    const filteredMembers = useMemo(() => {
        return searchTerm ? membersFuse.search(searchTerm).map((result) => result.item) : meFirstMembers
    }, [searchTerm, meFirstMembers])

    const selectedMember = useMemo(() => {
        if (!value) {
            return null
        }
        if (typeof value === 'string' || typeof value === 'number') {
            const propToCompare = typeof value === 'string' ? 'uuid' : 'id'
            return meFirstMembers.find((member) => member.user[propToCompare] === value)?.user ?? `${value}`
        }
        return value
    }, [value, meFirstMembers])

    const _onChange = (value: UserBasicType | null): void => {
        setShowPopover(false)
        onChange(value)
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            sameWidth={false}
            actionable
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={
                <div className="max-w-100 space-y-2 overflow-hidden">
                    <LemonInput
                        type="search"
                        placeholder="Search"
                        autoFocus
                        value={searchTerm}
                        onChange={setSearchTerm}
                        fullWidth
                    />
                    <ul className="space-y-px">
                        <li>
                            <LemonButton
                                status="stealth"
                                fullWidth
                                role="menuitem"
                                size="small"
                                onClick={() => _onChange(null)}
                            >
                                {defaultLabel}
                            </LemonButton>
                        </li>

                        {filteredMembers.map((member) => (
                            <li key={member.user.uuid}>
                                <LemonButton
                                    status="stealth"
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    icon={<ProfilePicture size="md" user={member.user} />}
                                    onClick={() => _onChange(member.user)}
                                >
                                    <span className="flex items-center justify-between gap-2 flex-1">
                                        <span>{fullName(member.user)}</span>
                                        <span className="text-muted-alt">
                                            {meFirstMembers[0] === member && `(you)`}
                                        </span>
                                    </span>
                                </LemonButton>
                            </li>
                        ))}

                        {filteredMembers.length === 0 ? (
                            <div className="p-2 text-muted-alt italic truncate border-t">
                                {searchTerm ? <span>No matches</span> : <span>No users</span>}
                            </div>
                        ) : null}
                    </ul>
                </div>
            }
        >
            <LemonButton status="stealth" {...buttonProps}>
                {typeof selectedMember === 'string' ? (
                    selectedMember
                ) : selectedMember ? (
                    <span>
                        {fullName(selectedMember)}
                        {meFirstMembers[0].user.uuid === selectedMember.uuid ? ` (you)` : ''}
                    </span>
                ) : (
                    defaultLabel
                )}
            </LemonButton>
        </LemonDropdown>
    )
}
