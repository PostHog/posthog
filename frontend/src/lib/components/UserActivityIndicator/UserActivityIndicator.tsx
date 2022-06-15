import clsx from 'clsx'
import React from 'react'
import { UserBasicType } from '~/types'
import { ProfilePicture } from '../ProfilePicture'
import { TZLabel } from '../TimezoneAware'
import './UserActivityIndicator.scss'

export interface UserActivityIndicatorProps {
    prefix?: string
    at: string | null | undefined
    by?: UserBasicType | null | undefined
    className?: string
}

export function UserActivityIndicator({
    at,
    by,
    prefix = 'Last modified',
    className,
}: UserActivityIndicatorProps): JSX.Element | null {
    return at || by ? (
        <div className={clsx('UserActivityIndicator', className)}>
            <div>
                {prefix}
                {at && ' '}
                {at && <TZLabel time={at} />}
                {by && ' by'}
            </div>
            {by && <ProfilePicture name={by.first_name} email={by.email} showName size="md" />}
        </div>
    ) : null
}
