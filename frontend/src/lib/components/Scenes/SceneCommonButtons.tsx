import { IconCopy, IconStar, IconStarFilled } from '@posthog/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

type SceneCommonButtonsButtonProps = {
    onClick?: () => void
    active?: boolean
}

type SceneCommonButtonsProps = {
    duplicate?: SceneCommonButtonsButtonProps
    favorite?: SceneCommonButtonsButtonProps
}

export function SceneCommonButtons({ duplicate, favorite }: SceneCommonButtonsProps): JSX.Element {
    return (
        <div className="grid grid-cols-2 gap-1">
            {favorite && (
                <ButtonPrimitive
                    onClick={favorite.onClick}
                    tooltip={favorite.active ? 'Remove from favorites' : 'Add to favorites'}
                    active={favorite.active}
                    fullWidth
                    className="justify-center"
                    menuItem
                >
                    {favorite.active ? <IconStarFilled className="text-warning" /> : <IconStar />}
                </ButtonPrimitive>
            )}

            {duplicate && (
                <ButtonPrimitive
                    onClick={duplicate.onClick}
                    tooltip="Duplicate"
                    fullWidth
                    className="justify-center"
                    menuItem
                >
                    <IconCopy />
                </ButtonPrimitive>
            )}
        </div>
    )
}
