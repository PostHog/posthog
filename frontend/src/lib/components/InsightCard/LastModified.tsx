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
}): JSX.Element | null {
    return at || by ? (
        <div className="LastModified">
            <div>
                Last modified{at && ' '}
                {at && <TZLabel time={at} />}
                {by && ' by'}
            </div>
            {by && <ProfilePicture name={by.first_name} email={by.email} showName size="md" />}
        </div>
    ) : null
}
