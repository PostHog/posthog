import {
    IconCopy,
    IconShare,
    IconExpand45,
    IconPin,
    IconPinFilled,
    IconRewindPlay,
    IconStar,
    IconStarFilled,
    IconComment,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneDataAttrKeyProps } from './utils'
import { useActions } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import posthog from 'posthog-js'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

type SceneCommonButtonsButtonProps = {
    onClick?: () => void
    active?: boolean
    to?: string
}

type SceneCommonButtonsProps = SceneDataAttrKeyProps & {
    duplicate?: SceneCommonButtonsButtonProps
    favorite?: SceneCommonButtonsButtonProps
    share?: SceneCommonButtonsButtonProps
    pinned?: SceneCommonButtonsButtonProps
    fullscreen?: SceneCommonButtonsButtonProps
    recordings?: SceneCommonButtonsButtonProps
    comment?: boolean
}

export function SceneCommonButtons({
    duplicate,
    favorite,
    share,
    pinned,
    fullscreen,
    recordings,
    comment,
    dataAttrKey,
}: SceneCommonButtonsProps): JSX.Element {
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
    const { openSidePanel } = useActions(sidePanelLogic)

    return (
        <div className="flex gap-1">
            {favorite && (
                <ButtonPrimitive
                    onClick={favorite.onClick}
                    tooltip={favorite.active ? 'Remove from favorites' : 'Add to favorites'}
                    active={favorite.active}
                    className="justify-center flex-1"
                    menuItem
                >
                    {favorite.active ? <IconStarFilled className="text-warning" /> : <IconStar />}
                </ButtonPrimitive>
            )}

            {comment && (
                <ButtonPrimitive
                    onClick={() => {
                        if (!hasDiscussions) {
                            posthog.updateEarlyAccessFeatureEnrollment('discussions', true)
                        }
                        openSidePanel(SidePanelTab.Discussion)
                    }}
                    tooltip="Comment"
                    fullWidth
                    className="justify-center"
                    menuItem
                >
                    <IconComment />
                </ButtonPrimitive>
            )}

            {share && (
                <ButtonPrimitive onClick={share.onClick} tooltip="Share" fullWidth className="justify-center" menuItem>
                    <IconShare />
                </ButtonPrimitive>
            )}

            {duplicate && (
                <ButtonPrimitive
                    onClick={duplicate.onClick}
                    tooltip="Duplicate"
                    className="justify-center flex-1"
                    menuItem
                    data-attr={`${dataAttrKey}-duplicate`}
                >
                    <IconCopy />
                </ButtonPrimitive>
            )}

            {pinned && (
                <ButtonPrimitive
                    onClick={pinned.onClick}
                    tooltip={pinned.active ? 'Unpin' : 'Pin'}
                    active={pinned.active}
                    className="justify-center flex-1"
                    menuItem
                    data-attr={`${dataAttrKey}-pin`}
                >
                    {pinned.active ? <IconPinFilled className="text-warning" /> : <IconPin />}
                </ButtonPrimitive>
            )}

            {fullscreen && (
                <ButtonPrimitive
                    onClick={fullscreen.onClick}
                    tooltip={fullscreen.active ? 'Exit fullscreen' : 'Fullscreen'}
                    active={fullscreen.active}
                    className="justify-center flex-1"
                    menuItem
                    data-attr={`${dataAttrKey}-fullscreen`}
                >
                    <IconExpand45 />
                </ButtonPrimitive>
            )}

            {recordings && (
                <Link
                    onClick={recordings.onClick}
                    to={recordings.to}
                    tooltip="View recordings"
                    className="justify-center flex-1"
                    buttonProps={{
                        menuItem: true,
                    }}
                    data-attr={`${dataAttrKey}-view-recordings`}
                >
                    <IconRewindPlay />
                </Link>
            )}
        </div>
    )
}
