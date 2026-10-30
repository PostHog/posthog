import './toggle-group.css'

import { Toggle as TogglePrimitive } from '@base-ui/react/toggle'
import { ToggleGroup as ToggleGroupPrimitive } from '@base-ui/react/toggle-group'
import { type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'
import { toggleVariants } from './toggle'
import { hasTooltipContent } from './with-tooltip'

const ToggleGroupContext = React.createContext<
    VariantProps<typeof toggleVariants> & {
        spacing?: number
        orientation?: 'horizontal' | 'vertical'
    }
>({
    size: 'default',
    variant: 'default',
    spacing: 0,
    orientation: 'horizontal',
})

const ToggleGroup = React.forwardRef<
    React.ComponentRef<typeof ToggleGroupPrimitive>,
    ToggleGroupPrimitive.Props &
        VariantProps<typeof toggleVariants> & {
            spacing?: number
            orientation?: 'horizontal' | 'vertical'
        }
>(function ToggleGroup({ className, variant, size, spacing = 0, orientation = 'horizontal', children, ...props }, ref) {
    return (
        <ToggleGroupPrimitive
            ref={ref}
            data-quill
            data-slot="toggle-group"
            data-variant={variant}
            data-size={size}
            data-spacing={spacing}
            data-orientation={orientation}
            style={{ '--gap': spacing } as React.CSSProperties}
            className={cn(
                'quill-toggle-group group/toggle-group flex w-fit flex-row items-center gap-[--spacing(var(--gap))] data-[orientation=vertical]:flex-col data-[orientation=vertical]:items-stretch',
                className
            )}
            {...props}
        >
            <ToggleGroupContext.Provider value={{ variant, size, spacing, orientation }}>
                {children}
            </ToggleGroupContext.Provider>
        </ToggleGroupPrimitive>
    )
})

const ToggleGroupItem = React.forwardRef<
    React.ComponentRef<typeof TogglePrimitive>,
    TogglePrimitive.Props &
        VariantProps<typeof toggleVariants> & {
            /** Disables the item and says why in a tooltip on hover. */
            disabledReason?: React.ReactNode
        }
>(function ToggleGroupItem(
    { className, children, variant = 'default', size = 'default', disabled, disabledReason, ...props },
    ref
) {
    const context = React.useContext(ToggleGroupContext)

    return (
        <TogglePrimitive
            ref={ref}
            data-slot="toggle-group-item"
            data-variant={context.variant || variant}
            data-size={context.size || size}
            data-spacing={context.spacing}
            className={cn(
                'quill-toggle-group__item',
                toggleVariants({
                    variant: context.variant || variant,
                    size: context.size || size,
                }),
                className
            )}
            {...props}
            disabled={disabled || hasTooltipContent(disabledReason)}
            render={(props) => <Button variant="outline" size={size} disabledReason={disabledReason} {...props} />}
        >
            {children}
        </TogglePrimitive>
    )
})

export { ToggleGroup, ToggleGroupItem }
