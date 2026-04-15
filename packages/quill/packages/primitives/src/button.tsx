import { Button as ButtonPrimitive } from '@base-ui/react/button'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from './lib/utils'

const buttonVariants = cva(
    "group/button cursor-pointer inline-flex shrink-0 items-center justify-center rounded-md border border-transparent bg-clip-padding text-xs/relaxed font-medium whitespace-nowrap transition-all duration-100 outline-none select-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 not-disabled:active:translate-y-px [&_kbd]:-mr-1 has-data-[slot=dot]:ps-1.5",
    {
        variants: {
            variant: {
                default:
                    'not-disabled:hover:bg-fill-hover hover:text-foreground aria-expanded:bg-fill-expanded aria-expanded:text-foreground data-[popup-open]:bg-fill-hover border-none not-hover:aria-selected:bg-fill-selected not-hover:aria-[checked=true]:bg-fill-selected data-highlighted:bg-fill-hover',
                primary: 'bg-secondary text-secondary-foreground not-disabled:hover:bg-secondary/80',
                outline:
                    'bg-accent/30 border-foreground/10 dark:border-foreground/15 not-disabled:hover:bg-accent/50 hover:text-foreground dark:hover:text-foreground aria-expanded:bg-fill-expanded aria-expanded:text-foreground data-[popup-open]:bg-input/50',
                destructive:
                    'bg-destructive/50 text-destructive-foreground not-disabled:hover:bg-destructive focus-visible:border-destructive/40 focus-visible:ring-destructive-foreground/60 data-[popup-open]:bg-destructive/20',
                link: 'text-primary underline-offset-4 hover:underline data-[popup-open]:underline',
                'link-muted':
                    'text-muted-foreground underline-offset-4 hover:underline data-[popup-open]:underline',
            },
            size: {
                default:
                    "h-7 gap-2 px-2 text-xs/relaxed has-data-[icon=inline-end]:pe-1.5 has-data-[icon=inline-start]:ps-1.5 [&_svg:not([class*='size-'])]:size-3.5",
                xs: "h-5 gap-1 rounded-sm px-2 text-[0.625rem] has-data-[icon=inline-end]:pe-1.5 has-data-[icon=inline-start]:ps-1.5 [&_svg:not([class*='size-'])]:size-2.5",
                sm: "h-6 gap-1 px-2 text-xs/relaxed has-data-[icon=inline-end]:pe-1.5 has-data-[icon=inline-start]:ps-1.5 [&_svg:not([class*='size-'])]:size-3",
                lg: "h-8 gap-2 px-2.5 text-xs/relaxed has-data-[icon=inline-end]:pe-2 has-data-[icon=inline-start]:ps-2 [&_svg:not([class*='size-'])]:size-4",
                icon: "size-7 [&_svg:not([class*='size-'])]:size-3.5",
                'icon-xs': "size-5 rounded-sm [&_svg:not([class*='size-'])]:size-2.5",
                'icon-sm': "size-6 [&_svg:not([class*='size-'])]:size-3",
                'icon-lg': "size-8 [&_svg:not([class*='size-'])]:size-4",
            },
            focusableWhenDisabled: {
                true: '',
                false: 'disabled:pointer-events-none',
            },
            left: {
                true: 'justify-start',
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
                data-slot="button"
                className={cn(buttonVariants({ variant, size, className, focusableWhenDisabled, left }))}
                {...props}
            />
        )
    }
)
Button.displayName = 'Button'

export { Button, buttonVariants }
