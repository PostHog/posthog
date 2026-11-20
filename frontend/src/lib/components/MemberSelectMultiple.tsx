import { useActions, useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { QuillMemberSelectMultiple } from 'lib/components/QuillMemberSelectMultiple'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { fullNameOrEmail } from 'lib/utils/strings'

import { membersLogic } from '~/models/membersLogic'
import { UserBasicType } from '~/types'

type UserIdType = string | number

export type MemberSelectMultipleProps = {
    idKey: 'email' | 'uuid' | 'id'
    value: UserIdType[]
    onChange: (values: UserBasicType[]) => void
}

export function MemberSelectMultiple({ idKey, value, onChange }: MemberSelectMultipleProps): JSX.Element {
    const { meFirstMembers, membersLoading } = useValues(membersLogic)

    const { ensureAllMembersLoaded } = useActions(membersLogic)
    useOnMountEffect(ensureAllMembersLoaded)
    const quillSurface = useQuillSurface()

    const options = meFirstMembers.map((member) => ({
        key: member.user[idKey].toString(),
        label: fullNameOrEmail(member.user),
        value: member.user[idKey].toString(),
    }))

    const selectMembers = (newValues: UserIdType[]): void => {
        const selectedUsers = meFirstMembers.filter((member) => newValues.includes(member.user[idKey].toString()))
        onChange(selectedUsers.map((member) => member.user))
    }

    if (quillSurface) {
        return (
            <QuillMemberSelectMultiple
                options={options}
                value={value.map((v) => v.toString())}
                loading={membersLoading}
                onChange={selectMembers}
            />
        )
    }

    return (
        <LemonInputSelect
            placeholder="Search for team members to add…"
            value={value.map((v) => v.toString())}
            loading={membersLoading}
            onChange={selectMembers}
            mode="multiple"
            options={options}
            data-attr="subscribed-users"
        />
    )
}
