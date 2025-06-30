import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { UserBasicType } from '~/types'
import { TZLabel } from '../TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

interface SceneActivityIndicatorProps {
    prefix?: string
    at?: string
    by?: UserBasicType | null | undefined
}

export function SceneActivityIndicator({
    at,
    by,
    prefix = 'Last modified',
}: SceneActivityIndicatorProps): JSX.Element | null {
    return at && by ? (
        <div>
            <LemonField.Pure label={prefix} className="gap-0">
                <span className="flex items-center gap-1 whitespace-normal flex-wrap">
                    <TZLabel time={at} className="w-fit" />
                    <span className="text-secondary">by</span>
                    <ProfilePicture user={by} showName size="md" />
                </span>
            </LemonField.Pure>
        </div>
    ) : null
}
