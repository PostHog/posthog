import { cva } from 'cva'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

export interface ToggleButtonPrimitiveProps {
    className?: string
    checked: boolean
    children: React.ReactNode
    tooltip?: string
    iconOnly?: boolean
    onCheckedChange: (checked: boolean) => void
}

const button = cva({
    variants: {
        checked: {
            true: 'bg-fill-highlight-100',
        },
    },
})

export function ToggleButtonPrimitive({
    className,
    checked,
    tooltip,
    children,
    iconOnly,
    onCheckedChange,
}: ToggleButtonPrimitiveProps): JSX.Element {
    return (
        <ButtonPrimitive
            iconOnly={iconOnly}
            tooltip={tooltip}
            className={button({ checked, className })}
            onClick={() => onCheckedChange(!checked)}
        >
            {children}
        </ButtonPrimitive>
    )
}
