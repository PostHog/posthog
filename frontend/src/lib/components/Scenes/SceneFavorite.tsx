import { IconStar, IconStarFilled } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from './utils'

interface SceneFavoriteProps extends SceneDataAttrKeyProps {
    onClick: () => void
    isFavorited: boolean
}

export function SceneFavorite({ dataAttrKey, onClick, isFavorited }: SceneFavoriteProps): JSX.Element {
    return (
        <ButtonPrimitive
            menuItem
            onClick={onClick}
            data-attr={`${dataAttrKey}-favorite-button`}
            tooltip={isFavorited ? 'Unfavorite' : 'Favorite'}
            active={isFavorited}
        >
            {isFavorited ? <IconStarFilled className="text-warning" /> : <IconStar />}
            Favorite
        </ButtonPrimitive>
    )
}
