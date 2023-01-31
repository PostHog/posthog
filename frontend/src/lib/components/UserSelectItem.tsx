import { UserBasicType, UserType } from '~/types'
import { LemonSelectMultipleOptionItem } from 'lib/lemon-ui/LemonSelectMultiple'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

export interface UserSelectItemProps {
    user: UserBasicType | UserType
}

export function UserSelectItem({ user }: UserSelectItemProps): JSX.Element {
    return (
        <span className="flex gap-2 items-center">
            <ProfilePicture name={user.first_name} email={user.email} size="sm" />
            <span>
                {user.first_name} <b>{`<${user.email}>`}</b>
            </span>
        </span>
    )
}

export function usersLemonSelectOptions(
    users: (UserBasicType | UserType)[],
    key: 'email' | 'uuid' = 'email'
): LemonSelectMultipleOptionItem[] {
    return users.map((user) => ({
        key: user[key],
        label: `${user.first_name} ${user.email}`,
        labelComponent: <UserSelectItem user={user} />,
    }))
}
