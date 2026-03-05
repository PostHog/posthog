import { IconStar, IconStarFilled } from '@posthog/icons'

import { ButtonPrimitive, DisabledReasonsObject } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from './utils'

interface SceneFavoriteProps extends SceneDataAttrKeyProps {
    onClick: () => void
    isFavorited: boolean
    disabledReasons?: DisabledReasonsObject
}

export function SceneFavorite({ dataAttrKey, onClick, isFavorited, disabledReasons }: SceneFavoriteProps): JSX.Element {
    return (
        <ButtonPrimitive
            menuItem
            onClick={onClick}
            data-attr={`${dataAttrKey}-favorite-button`}
            tooltip={isFavorited ? 'Unfavorite' : 'Favorite'}
            active={isFavorited}
            disabledReasons={disabledReasons}
        >
            {isFavorited ? <IconStarFilled className="text-warning" /> : <IconStar />}
            Favorite
        </ButtonPrimitive>
    )
}
