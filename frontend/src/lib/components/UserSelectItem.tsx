import { LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { fullName } from 'lib/utils/strings'

import { UserBasicType, UserType } from '~/types'

export interface UserSelectItemProps {
    user: UserBasicType | UserType
}

export function UserSelectItem({ user }: UserSelectItemProps): JSX.Element {
    return (
        <span className="ph-no-capture flex gap-2 items-center">
            <ProfilePicture user={user} size="sm" />
            <span>
                {fullName(user)} {user.email && <b>{`<${user.email}>`}</b>}
            </span>
        </span>
    )
}

export function usersLemonSelectOptions(
    users: (UserBasicType | UserType)[],
    key: 'email' | 'uuid' = 'email'
): LemonInputSelectOption[] {
    return users.map((user) => ({
        // An account without an email has no email key, so fall back to the uuid to keep options distinct.
        key: user[key] ?? user.uuid,
        label: `${fullName(user)} ${user.email ?? ''}`.trim(),
        labelComponent: <UserSelectItem user={user} />,
    }))
}
