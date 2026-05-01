import { Toggle as TogglePrimitive } from '@base-ui/react/toggle'
import { ToggleGroup as ToggleGroupPrimitive } from '@base-ui/react/toggle-group'
import { type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'
import './toggle-group.css'
import { toggleVariants } from './toggle'

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

function ToggleGroup({
    className,
    variant,
    size,
    spacing = 0,
    orientation = 'horizontal',
    children,
    ...props
}: ToggleGroupPrimitive.Props &
    VariantProps<typeof toggleVariants> & {
        spacing?: number
        orientation?: 'horizontal' | 'vertical'
    }): React.ReactElement {
    return (
        <ToggleGroupPrimitive
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
}

function ToggleGroupItem({
    className,
    children,
    variant = 'default',
    size = 'default',
    ...props
}: TogglePrimitive.Props & VariantProps<typeof toggleVariants>): React.ReactElement {
    const context = React.useContext(ToggleGroupContext)

    return (
        <TogglePrimitive
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
            render={(props) => <Button variant="outline" size={size} {...props} />}
        >
            {children}
        </TogglePrimitive>
    )
}

export { ToggleGroup, ToggleGroupItem }
