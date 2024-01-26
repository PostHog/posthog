import { LemonButton, LemonDropdown, LemonInput, ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { fullName } from 'lib/utils'
import { useEffect, useMemo, useState } from 'react'
import { searchableMembersLogic } from 'scenes/organization/membersV2Logic'

import { UserBasicType } from '~/types'

export type MemberSelectProps = {
    defaultLabel?: string
    // NOTE: Trying to cover a lot of different cases - if string we assume uuid, if number we assume id
    value: UserBasicType | string | number | null
    onChange: (value: UserBasicType | null) => void
}

export function MemberSelect({ defaultLabel = 'Any user', value, onChange }: MemberSelectProps): JSX.Element {
    const { meFirstMembers, filteredMembers, search } = useValues(searchableMembersLogic({ logicKey: 'select' }))
    const { setSearch } = useActions(searchableMembersLogic({ logicKey: 'select' }))
    const [showPopover, setShowPopover] = useState(false)

    const selectedMember = useMemo(() => {
        if (!value) {
            return null
        }
        if (typeof value === 'string' || typeof value === 'number') {
            const propToCompare = typeof value === 'string' ? 'uuid' : 'id'
            return meFirstMembers.find((member) => member[propToCompare] === value) ?? `${value}`
        }
        return value
    }, [value, meFirstMembers])

    const _onChange = (value: UserBasicType | null): void => {
        setShowPopover(false)
        onChange(value)
    }

    useEffect(() => {
        if (showPopover) {
            setSearch('')
        }
    }, [showPopover])

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
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                    <ul className="space-y-px">
                        <li>
                            <LemonButton fullWidth role="menuitem" size="small" onClick={() => _onChange(null)}>
                                {defaultLabel}
                            </LemonButton>
                        </li>

                        {filteredMembers.map((member) => (
                            <li key={member.uuid}>
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    icon={<ProfilePicture size="md" user={member} />}
                                    onClick={() => _onChange(member)}
                                >
                                    <span className="flex items-center justify-between gap-2 flex-1">
                                        <span>{fullName(member)}</span>
                                        <span className="text-muted-alt">
                                            {meFirstMembers[0] === member && `(you)`}
                                        </span>
                                    </span>
                                </LemonButton>
                            </li>
                        ))}

                        {filteredMembers.length === 0 ? (
                            <div className="p-2 text-muted-alt italic truncate border-t">
                                {search ? <span>No matches</span> : <span>No users</span>}
                            </div>
                        ) : null}
                    </ul>
                </div>
            }
        >
            <LemonButton size="small" type="secondary">
                {typeof selectedMember === 'string' ? (
                    selectedMember
                ) : selectedMember ? (
                    <span>
                        {fullName(selectedMember)}
                        {meFirstMembers[0].uuid === selectedMember.uuid ? ` (you)` : ''}
                    </span>
                ) : (
                    defaultLabel
                )}
            </LemonButton>
        </LemonDropdown>
    )
}
