import './UserActivityIndicator.scss'

import { ProfilePicture } from '@posthog/lemon-ui'
import clsx from 'clsx'

import { UserBasicType } from '~/types'

import { TZLabel } from '../TZLabel'

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
            <div className="flex gap-x-1">
                <span>{prefix}</span>
                {at && <TZLabel time={at} />}
                {by && <span> by</span>}
            </div>
            {by && <ProfilePicture user={by} showName size="md" />}
        </div>
    ) : null
}
