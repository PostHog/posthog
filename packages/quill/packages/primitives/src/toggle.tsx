import { Toggle as TogglePrimitive } from '@base-ui/react/toggle'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './toggle.css'
import { cn } from './lib/utils'

const toggleVariants = cva(
    'quill-toggle group/toggle inline-flex items-center justify-center gap-1 whitespace-nowrap',
    {
        variants: {
            variant: {
                default: 'quill-toggle--variant-default',
                outline: 'quill-toggle--variant-outline',
            },
            size: {
                default: 'quill-toggle--size-default',
                sm: 'quill-toggle--size-sm',
                lg: 'quill-toggle--size-lg',
                icon: 'quill-toggle--size-icon',
            },
        },
        defaultVariants: {
            variant: 'default',
            size: 'default',
        },
    }
)

function Toggle({
    className,
    variant = 'default',
    size = 'default',
    ...props
}: TogglePrimitive.Props & VariantProps<typeof toggleVariants>): React.ReactElement {
    return (
        <TogglePrimitive
            data-quill
            data-slot="toggle"
            className={cn(toggleVariants({ variant, size, className }))}
            {...props}
        />
    )
}

export { Toggle, toggleVariants }
