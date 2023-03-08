import clsx from 'clsx'
import { UserBasicType } from '~/types'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { TZLabel } from '../TZLabel'
import './UserActivityIndicator.scss'

export interface UserActivityIndicatorProps {
    prefix?: string
    at: string | null | undefined
    by?: UserBasicType | null | undefined
    className?: string
    showProfilePicture?: boolean
}

export function UserActivityIndicator({
    at,
    by,
    prefix = 'modified',
    className,
    showProfilePicture = true,
}: UserActivityIndicatorProps): JSX.Element | null {
    return at || by ? (
        <div className={clsx('UserActivityIndicator', className)}>
            <div>
                {prefix}
                {at && ' '}
                {at && <TZLabel time={at} />}
                {by && ' by'}
            </div>
            {by ? (
                <>
                    {showProfilePicture ? (
                        <ProfilePicture name={by.first_name} email={by.email} showName size="md" />
                    ) : (
                        <b className="ml-1">{by.first_name}</b>
                    )}
                </>
            ) : null}
        </div>
    ) : null
}
