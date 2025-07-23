import { IconCopy, IconExpand45, IconPin, IconPinFilled, IconStar, IconStarFilled } from '@posthog/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

type SceneCommonButtonsButtonProps = {
    onClick?: () => void
    active?: boolean
}

type SceneCommonButtonsProps = {
    duplicate?: SceneCommonButtonsButtonProps
    favorite?: SceneCommonButtonsButtonProps
    pinned?: SceneCommonButtonsButtonProps
    fullscreen?: SceneCommonButtonsButtonProps
}

export function SceneCommonButtons({ duplicate, favorite, pinned, fullscreen }: SceneCommonButtonsProps): JSX.Element {
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
                >
                    <IconExpand45 />
                </ButtonPrimitive>
            )}
        </div>
    )
}
