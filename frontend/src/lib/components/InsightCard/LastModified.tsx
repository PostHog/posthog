import React from 'react'
import { UserBasicType } from '~/types'
import { ProfilePicture } from '../ProfilePicture'
import { TZLabel } from '../TimezoneAware'

export function LastModified({
    at,
    by,
}: {
    at: string | null | undefined
    by?: UserBasicType | null | undefined
}): JSX.Element {
    return (
        <div className="LastModified">
            <div>Last modified {at && <TZLabel time={at} />} by</div>
            <ProfilePicture name={by?.first_name} email={by?.email} showName size="md" />
        </div>
    )
}
