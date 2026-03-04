import { IconHeart, IconHeartFilled, IconStar, IconStarFilled } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from './utils'

interface SceneFavoriteProps extends SceneDataAttrKeyProps {
    onClick: () => void
    isFavorited: boolean
}

export function SceneFavorite({ dataAttrKey, onClick, isFavorited }: SceneFavoriteProps): JSX.Element {
    const isAIFirst = useFeatureFlag('AI_FIRST')
    return (
        <ButtonPrimitive
            menuItem
            onClick={onClick}
            data-attr={`${dataAttrKey}-favorite-button`}
            tooltip={isFavorited ? 'Unfavorite' : 'Favorite'}
            active={isFavorited}
        >
            {isAIFirst ? (
                isFavorited ? (
                    <IconHeartFilled className="text-danger" />
                ) : (
                    <IconHeart />
                )
            ) : isFavorited ? (
                <IconStarFilled className="text-warning" />
            ) : (
                <IconStar />
            )}
            Favorite
        </ButtonPrimitive>
    )
}
