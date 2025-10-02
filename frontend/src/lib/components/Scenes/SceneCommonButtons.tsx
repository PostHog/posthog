import { useActions } from 'kea'
import posthog from 'posthog-js'

import {
    IconComment,
    IconCopy,
    IconExpand45,
    IconPin,
    IconPinFilled,
    IconRewindPlay,
    IconShare,
    IconStar,
    IconStarFilled,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { SceneDataAttrKeyProps } from './utils'

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
        <div className="grid grid-cols-2 gap-1">
            {favorite && (
                <ButtonPrimitive
                    onClick={favorite.onClick}
                    tooltip={favorite.active ? 'Remove from favorites' : 'Add to favorites'}
                    active={favorite.active}
                    menuItem
                    className="justify-center"
                >
                    {favorite.active ? <IconStarFilled className="text-warning" /> : <IconStar />}
                    Favorite
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
                    menuItem
                    className="justify-center"
                >
                    <IconComment />
                    Comment
                </ButtonPrimitive>
            )}

            {share && (
                <ButtonPrimitive
                    onClick={share.onClick}
                    tooltip="Share"
                    data-attr={`${dataAttrKey}-share`}
                    menuItem
                    className="justify-center"
                >
                    <IconShare />
                    Share
                </ButtonPrimitive>
            )}

            {duplicate && (
                <ButtonPrimitive
                    onClick={duplicate.onClick}
                    tooltip="Duplicate this resource"
                    data-attr={`${dataAttrKey}-duplicate`}
                    menuItem
                    className="justify-center"
                >
                    <IconCopy />
                    Duplicate
                </ButtonPrimitive>
            )}

            {pinned && (
                <ButtonPrimitive
                    onClick={pinned.onClick}
                    tooltip={pinned.active ? 'Unpin' : 'Pin'}
                    active={pinned.active}
                    data-attr={`${dataAttrKey}-pin`}
                    menuItem
                    className="justify-center"
                >
                    {pinned.active ? <IconPinFilled className="text-warning" /> : <IconPin />}
                    Pin
                </ButtonPrimitive>
            )}

            {fullscreen && (
                <ButtonPrimitive
                    onClick={fullscreen.onClick}
                    tooltip={fullscreen.active ? 'Exit fullscreen' : 'Fullscreen'}
                    active={fullscreen.active}
                    data-attr={`${dataAttrKey}-fullscreen`}
                    menuItem
                    className="justify-center"
                >
                    <IconExpand45 />
                    Fullscreen
                </ButtonPrimitive>
            )}

            {recordings && (
                <Link
                    onClick={recordings.onClick}
                    to={recordings.to}
                    tooltip="View recordings"
                    buttonProps={{
                        menuItem: true,
                        className: 'justify-center',
                    }}
                    data-attr={`${dataAttrKey}-view-recordings`}
                    target="_blank"
                >
                    <IconRewindPlay />
                    View recordings
                </Link>
            )}
        </div>
    )
}
