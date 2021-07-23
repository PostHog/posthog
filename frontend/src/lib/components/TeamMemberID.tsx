import React from 'react'
import { UserBasicType } from '~/types'
import { ProfilePicture } from './ProfilePicture'

export function TeamMemberID({ person }: { person?: UserBasicType | null }): JSX.Element {
    return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {person ? (
                <>
                    <ProfilePicture name={person?.first_name} email={person?.email} size="md" />
                    <span style={{ marginLeft: 4 }}>{person?.first_name || person?.email}</span>
                </>
            ) : (
                <span className="text-muted">Unknown</span>
            )}
        </div>
    )
}
