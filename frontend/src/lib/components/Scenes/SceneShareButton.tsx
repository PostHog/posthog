import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { SceneDataAttrKeyProps } from './utils'

type SceneShareButtonProps = SceneDataAttrKeyProps & {
    buttonProps?: Omit<ButtonPrimitiveProps, 'children' | 'data-attr'>
    children?: React.ReactNode
}

export function SceneShareButton({ buttonProps, children, dataAttrKey }: SceneShareButtonProps): JSX.Element {
    return (
        <ButtonPrimitive {...buttonProps} data-attr={`${dataAttrKey}-share-button`}>
            {children}
        </ButtonPrimitive>
    )
}
