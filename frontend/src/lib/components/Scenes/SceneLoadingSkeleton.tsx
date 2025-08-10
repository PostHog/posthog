import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'

export function SceneLoadingSkeleton({ fullWidth = true }: Pick<ButtonPrimitiveProps, 'fullWidth'>): JSX.Element {
    return (
        <div className="flex flex-col gap-px">
            <WrappingLoadingSkeleton fullWidth={false}>
                <Label intent="menu" aria-hidden>
                    Some label text
                </Label>
            </WrappingLoadingSkeleton>

            <WrappingLoadingSkeleton fullWidth={fullWidth}>
                <ButtonPrimitive inert aria-hidden>
                    Loading...
                </ButtonPrimitive>
            </WrappingLoadingSkeleton>
        </div>
    )
}
