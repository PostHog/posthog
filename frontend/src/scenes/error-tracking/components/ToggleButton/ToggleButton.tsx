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
            true: 'not-disabled:bg-zinc-700 not-disabled:hover:bg-zinc-700 dark:not-disabled:bg-zinc-300 dark:not-disabled:hover:bg-zinc-300 text-primary-inverse',
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
