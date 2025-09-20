import { IconShare } from '@posthog/icons'

import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from './utils'

type SceneShareButtonProps = SceneDataAttrKeyProps & {
    buttonProps?: Omit<ButtonPrimitiveProps, 'children' | 'data-attr'>
}

export function SceneShareButton({ buttonProps, dataAttrKey }: SceneShareButtonProps): JSX.Element {
    return (
        <ButtonPrimitive {...buttonProps} data-attr={`${dataAttrKey}-share-button`}>
            <IconShare />
            Share or embed
        </ButtonPrimitive>
    )
}
