import { LemonButton, LemonButtonProps, LemonDropdown, LemonInput, ProfilePicture } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useMemo, useState } from 'react'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

export type MemberSelectProps = Pick<LemonButtonProps, 'size' | 'type'> & {
    defaultLabel?: string
    // NOTE: Trying to cover a lot of legacy cases - if string we assume uuid, if number we assume id
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
                <div className="max-w-160 space-y-2">
                    <LemonInput
                        type="search"
                        placeholder="Search"
                        autoFocus
                        value={searchTerm}
                        onChange={setSearchTerm}
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
                                    icon={
                                        <ProfilePicture
                                            size="md"
                                            name={member.user.first_name}
                                            email={member.user.email}
                                        />
                                    }
                                    onClick={() => _onChange(member.user)}
                                >
                                    <span className="flex items-center justify-between gap-2 flex-1">
                                        <span>{member.user.first_name}</span>
                                        <span className="text-muted-alt">
                                            {meFirstMembers[0] === member && `(you)`}
                                        </span>
                                    </span>
                                </LemonButton>
                            </li>
                        ))}

                        {filteredMembers.length === 0 ? (
                            <span className="p-2 text-muted-alt italic">
                                {searchTerm ? <span>No matches for "{searchTerm}"</span> : <span>No users</span>}
                            </span>
                        ) : null}
                    </ul>
                </div>
            }
        >
            <LemonButton {...buttonProps}>
                {typeof selectedMember === 'string' ? (
                    selectedMember
                ) : selectedMember ? (
                    <span>
                        {selectedMember.first_name}
                        {meFirstMembers[0].user.uuid === selectedMember.uuid ? ` (you)` : ''}
                    </span>
                ) : (
                    defaultLabel
                )}
            </LemonButton>
        </LemonDropdown>

        // <LemonSelect
        //     options={[
        //         { value: DEFAULT_FILTERS.createdBy, label: DEFAULT_FILTERS.createdBy },
        //         ...meFirstMembers.map((x) => ({
        //             value: x.user.uuid,
        //             label: x.user.first_name,
        //         })),
        //     ]}
        //     size="small"
        //     value={filters.createdBy}
        //     onChange={(v): void => {
        //         setFilters({ createdBy: v || DEFAULT_FILTERS.createdBy })
        //     }}
        //     dropdownMatchSelectWidth={false}
        //     {...selectProps}
        // />
    )
}
