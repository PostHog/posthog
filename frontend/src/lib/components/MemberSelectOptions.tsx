import { LemonButton } from '@posthog/lemon-ui'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'

import type { OrganizationMemberType } from '~/types'

import type { MemberSelectProps } from './MemberSelect'
import { MemberSelectRow } from './MemberSelectRow'

type MemberSelectOptionsProps = {
    extraOptions: NonNullable<MemberSelectProps['extraOptions']>
    allowNone: boolean
    defaultLabel: string
    members: OrganizationMemberType[]
    currentUserUuid?: string
    options: MemberSelectProps['options']
    optionsLoading: MemberSelectProps['optionsLoading']
    membersLoading: boolean
    searchValue: string
    onChange: MemberSelectProps['onChange']
    onSelectOption: MemberSelectProps['onSelectOption']
    onClose: () => void
}

export function MemberSelectOptions({
    extraOptions,
    allowNone,
    defaultLabel,
    members,
    currentUserUuid,
    options,
    optionsLoading,
    membersLoading,
    searchValue,
    onChange,
    onSelectOption,
    onClose,
}: MemberSelectOptionsProps): JSX.Element {
    const displayedOptions =
        options && !searchValue && currentUserUuid
            ? [...options].sort(
                  (first, second) => Number(second.uuid === currentUserUuid) - Number(first.uuid === currentUserUuid)
              )
            : options

    return (
        <ul className="deprecated-space-y-px">
            {extraOptions.map((option) => (
                <li key={option.label}>
                    <LemonButton
                        fullWidth
                        role="menuitem"
                        size="small"
                        onClick={() => {
                            onClose()
                            option.onClick()
                        }}
                    >
                        {option.label}
                    </LemonButton>
                </li>
            ))}
            {allowNone && (
                <li>
                    <LemonButton fullWidth role="menuitem" size="small" onClick={() => onChange(null)}>
                        {defaultLabel}
                    </LemonButton>
                </li>
            )}

            {members.map((member) => (
                <MemberSelectRow
                    key={member.user.uuid}
                    member={member}
                    isYou={member.user.uuid === currentUserUuid}
                    onClick={() => onChange(member.user)}
                />
            ))}

            {displayedOptions?.map((option) => (
                <li key={option.uuid}>
                    <LemonButton
                        fullWidth
                        role="menuitem"
                        size="small"
                        icon={<ProfilePicture size="md" user={{ first_name: option.name, email: option.email }} />}
                        onClick={() => {
                            onClose()
                            onSelectOption?.(option.uuid, option.name || option.email)
                        }}
                    >
                        <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
                            <span className="min-w-0 flex-1 truncate">{option.name || option.email}</span>
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
    )
}
