import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'

type SceneShareButtonProps = {
    buttonProps?: Omit<ButtonPrimitiveProps, 'children'>
    onClick?: () => void
    children?: React.ReactNode
}

export function SceneShareButton({ buttonProps, children }: SceneShareButtonProps): JSX.Element {
    return <ButtonPrimitive {...buttonProps}>{children}</ButtonPrimitive>
}
