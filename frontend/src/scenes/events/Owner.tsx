import { ProfilePicture } from 'lib/components/ProfilePicture'
import React, { CSSProperties } from 'react'
import { UserBasicType } from '~/types'

export function Owner({ user, style = {} }: { user?: UserBasicType | null; style?: CSSProperties }): JSX.Element {
    return (
        <>
            {user?.uuid ? (
                <div style={{ display: 'flex', alignItems: 'center', flexDirection: 'row' }}>
                    <ProfilePicture name={user.first_name} email={user.email} size="sm" />
                    <span style={{ paddingLeft: 8, ...style }}>{user.first_name}</span>
                </div>
            ) : (
                <span className="text-muted" style={{ fontStyle: 'italic', ...style }}>
                    No owner
                </span>
            )}
        </>
    )
}
