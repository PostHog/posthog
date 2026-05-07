import { NumberField } from '@base-ui/react/number-field'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { Button } from './button'
import './input-group.css'
import { Input } from './input'
import { cn } from './lib/utils'
import { Textarea } from './textarea'

const InputGroup = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(({ className, ...props }, ref) => {
    return (
        <div
            ref={ref}
            data-quill
            data-slot="input-group"
            role="group"
            className={cn('quill-input-group group/input-group flex items-center', className)}
            {...props}
        />
    )
})
InputGroup.displayName = 'InputGroup'

const inputGroupAddonVariants = cva(
    'quill-input-group__addon group/input-group-addon empty:hidden flex h-auto items-center justify-center gap-1 select-none whitespace-nowrap',
    {
        variants: {
            align: {
                'inline-start': 'quill-input-group__addon--align-inline-start',
                'inline-end': 'quill-input-group__addon--align-inline-end',
                'block-start': 'quill-input-group__addon--align-block-start justify-start',
                'block-end': 'quill-input-group__addon--align-block-end justify-start',
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

const inputGroupButtonVariants = cva('quill-input-group__button flex items-center gap-2', {
    variants: {
        size: {
            xs: 'quill-input-group__button--size-xs',
            sm: 'quill-input-group__button--size-sm',
            'icon-xs': 'quill-input-group__button--size-icon-xs',
            'icon-sm': 'quill-input-group__button--size-icon-sm',
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
    return <span className={cn('quill-input-group__text flex items-end gap-2', className)} {...props} />
}

const InputGroupInput = React.forwardRef<HTMLInputElement, React.ComponentProps<'input'>>(
    ({ className, ...props }, ref) => {
        return (
            <Input
                ref={ref}
                data-slot="input-group-control"
                className={cn('quill-input-group__control', className)}
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
            className={cn('quill-input-group__control quill-input-group__control--textarea', className)}
            {...props}
        />
    )
}

interface InputGroupNumberInputProps extends Omit<NumberField.Root.Props, 'className' | 'children'> {
    className?: string
    inputRef?: React.Ref<HTMLInputElement>
}

function InputGroupNumberInput({
    className,
    inputRef,
    ...rootProps
}: InputGroupNumberInputProps): React.ReactElement {
    return (
        <NumberField.Root {...rootProps}>
            <NumberField.ScrubArea data-slot="input-group-scrub-area" className="cursor-ew-resize">
                <NumberField.Input
                    ref={inputRef}
                    data-slot="input-group-control"
                    className={cn(
                        'quill-input-group__control h-8 w-full min-w-0 px-2 py-0.5 text-xs tabular-nums text-center outline-none placeholder:text-muted-foreground disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
                        className
                    )}
                />
            </NumberField.ScrubArea>
        </NumberField.Root>
    )
}

export { InputGroup, InputGroupAddon, InputGroupButton, InputGroupText, InputGroupInput, InputGroupNumberInput, InputGroupTextarea }
