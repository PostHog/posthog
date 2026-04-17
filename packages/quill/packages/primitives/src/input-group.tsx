import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { Button } from './button'
import { Input } from './input'
import { cn } from './lib/utils'
import { Textarea } from './textarea'

const InputGroup = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(({ className, ...props }, ref) => {
    return (
        <div
            ref={ref}
            data-slot="input-group"
            role="group"
            className={cn(
                'group/input-group relative flex h-8 w-full min-w-0 items-center rounded-md border border-input bg-input/20 dark:bg-input/30 transition-colors outline-none in-data-[slot=combobox-content]:focus-within:border-inherit in-data-[slot=combobox-content]:focus-within:ring-0 has-data-[align=block-end]:rounded-md has-data-[align=block-start]:rounded-md has-[[data-slot=input-group-control]:focus-visible]:border-ring has-[[data-slot=input-group-control]:focus-visible]:ring-2 has-[[data-slot=input-group-control]:focus-visible]:ring-ring/30 has-[[data-slot][aria-invalid=true]]:bg-destructive/50 has-[[data-slot][aria-invalid=true]]:border-destructive-foreground/30 has-[[data-slot][aria-invalid=true]]:focus-within:ring-destructive-foreground/50 has-[[data-slot][aria-invalid=true]]:focus-within:ring-3 has-[textarea]:rounded-md has-[>[data-align=block-end]]:h-auto has-[>[data-align=block-end]]:flex-col has-[>[data-align=block-start]]:h-auto has-[>[data-align=block-start]]:flex-col has-[>textarea]:h-auto has-[>[data-align=block-end]]:[&>input]:pt-3 has-[>[data-align=block-start]]:[&>input]:pb-3 has-[>[data-align=inline-end]]:[&>input]:pe-1.5 has-[>[data-align=inline-start]]:[&>input]:ps-1.5 aria-disabled:pointer-events-none aria-disabled:cursor-not-allowed aria-disabled:opacity-50',
                className
            )}
            {...props}
        />
    )
})
InputGroup.displayName = 'InputGroup'

const inputGroupAddonVariants = cva(
    "group/input-group-addon flex h-auto cursor-text items-center justify-center gap-1 py-2 text-xs/relaxed font-medium text-muted-foreground select-none group-data-[disabled=true]/input-group:opacity-50 **:data-[slot=kbd]:rounded-[calc(var(--radius-sm)-2px)] **:data-[slot=kbd]:bg-muted-foreground/10 **:data-[slot=kbd]:px-1 **:data-[slot=kbd]:text-[0.625rem] [&>svg:not([class*='size-'])]:size-3.5",
    {
        variants: {
            align: {
                'inline-start': 'order-first ps-2 has-[>button]:ms-[-0.275rem] has-[>kbd]:ms-[-0.275rem]',
                'inline-end':
                    'order-last pe-2 has-[>button]:me-[-0.275rem] has-[>button[data-size="sm"]]:me-[-0.475rem] has-[>kbd]:me-[-0.275rem]',
                'block-start':
                    'order-first w-full justify-start px-2 pt-2 group-has-[>input]/input-group:pt-2 [.border-b]:pb-2',
                'block-end':
                    'order-last w-full justify-start px-2 pb-2 group-has-[>input]/input-group:pb-2 [.border-t]:pt-2',
            },
        },
        defaultVariants: {
            align: 'inline-start',
        },
    }
)

function InputGroupAddon({
    className,
    align = 'inline-start',
    ...props
}: React.ComponentProps<'div'> & VariantProps<typeof inputGroupAddonVariants>): React.ReactElement {
    return (
        <div
            role="group"
            data-slot="input-group-addon"
            data-align={align}
            className={cn(inputGroupAddonVariants({ align }), className)}
            onClick={(e) => {
                if ((e.target as HTMLElement).closest('button')) {
                    return
                }
                e.currentTarget.parentElement?.querySelector('input')?.focus()
            }}
            {...props}
        />
    )
}

const inputGroupButtonVariants = cva('flex items-center gap-2 rounded-md text-xs/relaxed shadow-none', {
    variants: {
        size: {
            xs: "h-5 gap-1 rounded-[calc(var(--radius-sm)-2px)] px-1 [&>svg:not([class*='size-'])]:size-3",
            sm: 'gap-1',
            'icon-xs': 'size-6 p-0 has-[>svg]:p-0',
            'icon-sm': 'size-7 p-0 has-[>svg]:p-0',
        },
    },
    defaultVariants: {
        size: 'xs',
    },
})

const InputGroupButton = React.forwardRef<
    HTMLButtonElement,
    Omit<React.ComponentProps<typeof Button>, 'size' | 'type'> &
        VariantProps<typeof inputGroupButtonVariants> & {
            type?: 'button' | 'submit' | 'reset'
        }
>(({ className, type = 'button', variant, size = 'sm', ...props }, ref) => {
    return (
        <Button
            ref={ref}
            type={type}
            data-size={size}
            variant={variant}
            className={cn(inputGroupButtonVariants({ size }), className)}
            {...props}
        />
    )
})
InputGroupButton.displayName = 'InputGroupButton'

function InputGroupText({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return (
        <span
            className={cn(
                "flex items-end gap-2 text-xs/relaxed text-muted-foreground [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 relative",
                className
            )}
            {...props}
        />
    )
}

const InputGroupInput = React.forwardRef<HTMLInputElement, React.ComponentProps<'input'>>(
    ({ className, ...props }, ref) => {
        return (
            <Input
                ref={ref}
                data-slot="input-group-control"
                className={cn(
                    'flex-1 rounded-none border-0 bg-transparent shadow-none ring-0 focus-visible:ring-0 aria-invalid:ring-0 focus-visible:aria-invalid:ring-0 dark:bg-transparent',
                    className
                )}
                {...props}
            />
        )
    }
)
InputGroupInput.displayName = 'InputGroupInput'

function InputGroupTextarea({ className, ...props }: React.ComponentProps<'textarea'>): React.ReactElement {
    return (
        <Textarea
            data-slot="input-group-control"
            className={cn(
                'flex-1 resize-none rounded-none border-0 bg-transparent py-2 shadow-none ring-0 focus-visible:ring-0 aria-invalid:ring-0 focus-visible:aria-invalid:ring-0 aria-invalid:bg-transparent dark:bg-transparent',
                className
            )}
            {...props}
        />
    )
}

export { InputGroup, InputGroupAddon, InputGroupButton, InputGroupText, InputGroupInput, InputGroupTextarea }
