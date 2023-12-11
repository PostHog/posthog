import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { CSSProperties } from 'react'

import { UserBasicType } from '~/types'

export function Owner({ user, style = {} }: { user?: UserBasicType | null; style?: CSSProperties }): JSX.Element {
    return (
        <>
            {user?.uuid ? (
                <div className="flex items-center flex-row">
                    <ProfilePicture name={user.first_name} email={user.email} size="sm" />
                    <span className="pl-2" style={style}>
                        {user.first_name}
                    </span>
                </div>
            ) : (
                <span className="text-muted italic" style={style}>
                    No owner
                </span>
            )}
        </>
    )
}
