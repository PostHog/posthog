import {
    IconCopy,
    IconExpand45,
    IconPin,
    IconPinFilled,
    IconRewindPlay,
    IconStar,
    IconStarFilled,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneDataAttrKeyProps } from './utils'

type SceneCommonButtonsButtonProps = {
    onClick?: () => void
    active?: boolean
    to?: string
}

type SceneCommonButtonsProps = SceneDataAttrKeyProps & {
    duplicate?: SceneCommonButtonsButtonProps
    favorite?: SceneCommonButtonsButtonProps
    pinned?: SceneCommonButtonsButtonProps
    fullscreen?: SceneCommonButtonsButtonProps
    recordings?: SceneCommonButtonsButtonProps
}

export function SceneCommonButtons({
    duplicate,
    favorite,
    pinned,
    fullscreen,
    recordings,
    dataAttrKey,
}: SceneCommonButtonsProps): JSX.Element {
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
