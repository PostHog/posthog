import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { UserBasicType } from '~/types'
import { TZLabel } from '../TZLabel'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

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
    return at || by ? (
        <ScenePanelLabel title={prefix}>
            <span className="flex items-center gap-1 whitespace-normal flex-wrap mx-button-padding-x">
                {at && <TZLabel time={at} className="w-fit" />}
                {by && (
                    <>
                        <span className="text-secondary-foreground">by</span>
                        <ProfilePicture user={by} showName size="md" />
                    </>
                )}
            </span>
        </ScenePanelLabel>
    ) : null
}
