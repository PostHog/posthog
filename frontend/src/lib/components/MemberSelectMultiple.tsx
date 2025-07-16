import { LemonInputSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { fullName } from 'lib/utils'
import { useEffect } from 'react'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

type UserIdType = string | number

export type MemberSelectMultipleProps = {
    idKey: 'email' | 'uuid' | 'id'
    value: UserIdType[]
    onChange: (values: UserBasicType[]) => void
}

export function MemberSelectMultiple({ idKey, value, onChange }: MemberSelectMultipleProps): JSX.Element {
    const { filteredMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    useEffect(() => {
        ensureAllMembersLoaded()
    }, [])

    const options = filteredMembers.map((member) => ({
        key: member.user[idKey].toString(),
        label: fullName(member.user),
        value: member.user[idKey].toString(),
    }))

    return (
        <LemonInputSelect
            placeholder="Search for team members to add…"
            value={value.map((v) => v.toString())}
            loading={membersLoading}
            onChange={(newValues: UserIdType[]) => {
                const selectedUsers = filteredMembers.filter((member) =>
                    newValues.includes(member.user[idKey].toString())
                )
                onChange(selectedUsers.map((member) => member.user))
            }}
            mode="multiple"
            options={options}
            data-attr="subscribed-users"
        />
    )
}
