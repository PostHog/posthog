import { ProfilePicture } from 'lib/components/ProfilePicture'
import React from 'react'
import { UserBasicType } from '~/types'

export function Owner({ user }: { user?: UserBasicType | null }): JSX.Element {
    return (
        <>
            {user?.uuid ? (
                <div style={{ display: 'flex', alignItems: 'center', flexDirection: 'row' }}>
                    <ProfilePicture name={user.first_name} email={user.email} size="sm" />
                    <span style={{ paddingLeft: 8 }}>{user.first_name}</span>
                </div>
            ) : (
                <span className="text-muted" style={{ fontStyle: 'italic' }}>
                    No Owner
                </span>
            )}
        </>
    )
}
