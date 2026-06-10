import { Button as ButtonPrimitive } from '@base-ui/react/button'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './button.css'
import { cn } from './lib/utils'

const buttonVariants = cva(
    'quill-button group/button inline-flex shrink-0 items-center justify-center whitespace-nowrap',
    {
        variants: {
            variant: {
                default: 'quill-button--variant-default',
                primary: 'quill-button--variant-primary',
                outline: 'quill-button--variant-outline',
                destructive: 'quill-button--variant-destructive',
                link: 'quill-button--variant-link',
                'link-muted': 'quill-button--variant-link-muted',
            },
            size: {
                default: 'quill-button--size-default',
                xs: 'quill-button--size-xs',
                sm: 'quill-button--size-sm',
                lg: 'quill-button--size-lg',
                icon: 'quill-button--size-icon',
                'icon-xs': 'quill-button--size-icon-xs',
                'icon-sm': 'quill-button--size-icon-sm',
                'icon-lg': 'quill-button--size-icon-lg',
            },
            focusableWhenDisabled: {
                true: '',
                false: 'quill-button--not-focusable-when-disabled',
            },
            left: {
                true: 'justify-start',
                false: '',
            },
            inert: {
                true: 'quill-button--inert',
                false: '',
            },
        },
        defaultVariants: {
            variant: 'default',
            size: 'default',
        },
    }
)

export type ButtonProps = ButtonPrimitive.Props & VariantProps<typeof buttonVariants>

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    (
        { className, variant = 'default', size = 'default', focusableWhenDisabled = true, left = false, ...props },
        ref
    ) => {
        return (
            <ButtonPrimitive
                ref={ref}
                data-quill
                data-slot="button"
                data-size={size}
                className={cn(buttonVariants({ variant, size, className, focusableWhenDisabled, left }))}
                {...props}
            />
        )
    }
)
Button.displayName = 'Button'

export { Button, buttonVariants }
