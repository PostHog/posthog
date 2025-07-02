import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Label } from 'lib/ui/Label/Label'
import { UserBasicType } from '~/types'
import { TZLabel } from '../TZLabel'

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
            <div className="gap-0">
                <Label intent="menu">{prefix}</Label>
                <span className="flex items-center gap-1 whitespace-normal flex-wrap">
                    <TZLabel time={at} className="w-fit" />
                    <span className="text-secondary">by</span>
                    <ProfilePicture user={by} showName size="md" />
                </span>
            </div>
        </div>
    ) : null
}
