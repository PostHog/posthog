import { IconX } from '@posthog/icons'
import { cva } from 'class-variance-authority'
import { cn } from 'lib/utils/styles'
import * as React from 'react'

import { Button } from '../Button/Button'

const inputVariants = cva(
    `
        element-input
        flex h-9 w-full items-center
        rounded-sm border
        px-2 py-1
        text-sm
        ring-offset-background
        file:border-0
        file:bg-transparent
        file:text-sm
        file:font-medium
        placeholder:text-muted-foreground
        focus-visible:outline-none
        focus-visible:ring-2
        focus-visible:ring-ring
        focus-visible:ring-offset-2
        disabled:cursor-not-allowed
        disabled:opacity-50
  `,
    {
        variants: {
            hasIconLeft: {
                true: 'pl-0',
                false: '',
            },
            hasIconRight: {
                true: 'pr-0',
                false: '',
            },
        },

        defaultVariants: {
            hasIconLeft: false,
            hasIconRight: false,
        },
    }
)

export const Input = React.forwardRef<
    HTMLInputElement,
    React.InputHTMLAttributes<HTMLInputElement> & {
        iconLeft?: React.ReactNode
        iconRight?: React.ReactNode
        clearable?: boolean
        id: string
    }
>(({ className, type, iconLeft, iconRight, id, clearable, onChange, value, ...props }, ref) => {
    const handleClear = (): void => {
        if (onChange) {
            onChange({ target: { value: '' } } as React.ChangeEvent<HTMLInputElement>)
        }
    }

    return (
        <label
            htmlFor={id}
            className={cn(
                inputVariants({ hasIconLeft: !!iconLeft, hasIconRight: !!iconRight || clearable, className })
            )}
        >
            {iconLeft && (
                <Button iconOnly size="sm" insideInput disabled className="flex-shrink-0">
                    {iconLeft}
                </Button>
            )}
            <input
                type={type}
                className="w-full bg-transparent border-none outline-none p-0 focus:ring-0 focus:ring-offset-0"
                ref={ref}
                id={id}
                onChange={onChange}
                value={value}
                {...props}
            />
            {iconRight && (
                <Button iconOnly size="sm" insideInput disabled className="flex-shrink-0">
                    {iconRight}
                </Button>
            )}
            {clearable && (
                <Button
                    iconOnly
                    size="sm"
                    insideInput
                    onClick={handleClear}
                    className="flex-shrink-0 rounded-tl-none rounded-tr-[3px] rounded-br-[3px] rounded-bl-none [&>svg]:top-[-1px]"
                >
                    <IconX />
                </Button>
            )}
        </label>
    )
})

Input.displayName = 'Input'
