import { LemonInputSelectOption, ProfilePicture } from '@posthog/lemon-ui'

import { UserBasicType, UserType } from '~/types'

export interface UserSelectItemProps {
    user: UserBasicType | UserType
}

export function UserSelectItem({ user }: UserSelectItemProps): JSX.Element {
    return (
        <span className="flex gap-2 items-center">
            <ProfilePicture user={user} size="sm" />
            <span>
                {user.first_name} <b>{`<${user.email}>`}</b>
            </span>
        </span>
    )
}

export function usersLemonSelectOptions(
    users: (UserBasicType | UserType)[],
    key: 'email' | 'uuid' = 'email'
): LemonInputSelectOption[] {
    return users.map((user) => ({
        key: user[key],
        label: `${user.first_name} ${user.email}`,
        labelComponent: <UserSelectItem user={user} />,
    }))
}
