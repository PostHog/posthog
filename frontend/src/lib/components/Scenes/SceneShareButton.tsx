import { IconShare } from '@posthog/icons'

import { ButtonPrimitive, ButtonPrimitiveProps, DisabledReasonsObject } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from './utils'

type SceneShareButtonProps = SceneDataAttrKeyProps & {
    buttonProps?: Omit<ButtonPrimitiveProps, 'children' | 'data-attr'>
    disabledReasons?: DisabledReasonsObject
}

export function SceneShareButton({ buttonProps, dataAttrKey, disabledReasons }: SceneShareButtonProps): JSX.Element {
    return (
        <ButtonPrimitive {...buttonProps} data-attr={`${dataAttrKey}-share-button`} disabledReasons={disabledReasons}>
            <IconShare />
            Share or embed
        </ButtonPrimitive>
    )
}
