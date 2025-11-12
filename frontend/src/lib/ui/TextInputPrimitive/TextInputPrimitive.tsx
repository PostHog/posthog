import './TextInputPrimitive.css'

import { type VariantProps, cva } from 'cva'
import { forwardRef, useCallback, useEffect, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

export const textInputVariants = cva({
    base: 'text-input-primitive w-full rounded border text-sm outline-none relative',
    variants: {
        variant: {
            default: 'border-primary bg-surface-primary hover:border-secondary focus-visible:border-secondary',
            invisible: 'border-transparent bg-transparent hover:border-transparent',
        },
        size: {
            sm: '',
            default: '',
            lg: '',
            auto: '',
        },
        hasSuffix: {
            true: 'pr-10',
            false: '',
        },
        error: {
            true: 'border-error bg-fill-error-highlight hover:border-error focus-visible:border-error',
            false: '',
        },
    },
    defaultVariants: {
        variant: 'default',
        size: 'default',
        error: false,
    },
    compoundVariants: [
        // Paddings
        {
            variant: 'default',
            size: 'sm',
            className: 'text-input-primitive--padding-sm',
        },
        {
            variant: 'invisible',
            size: 'default',
            className: 'text-input-primitive--padding-base',
        },
        {
            variant: 'default',
            size: 'lg',
            className: 'text-input-primitive--padding-lg',
        },
        // Heights
        {
            variant: 'default',
            size: 'sm',
            className: 'text-input-primitive--height-sm',
        },
        {
            variant: 'default',
            size: 'default',
            className: 'text-input-primitive--height-base',
        },
        {
            variant: 'default',
            size: 'lg',
            className: 'text-input-primitive--height-lg',
        },
        {
            variant: 'invisible',
            size: ['sm', 'default', 'lg'],
            className: 'h-full',
        },
    ],
})

export type TextInputBaseProps = {
    onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void
    autoFocus?: boolean
    dataAttr?: string
    className?: string
    suffix?: React.ReactNode
} & VariantProps<typeof textInputVariants>

export interface TextInputPrimitiveProps
    extends TextInputBaseProps,
        Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'> {}

export const TextInputPrimitive = forwardRef<HTMLInputElement, TextInputPrimitiveProps>((props, ref) => {
    const { autoFocus, variant, size = 'default', type = 'text', className, suffix, ...rest } = props

    const internalRef = useRef<HTMLInputElement>(null)

    const mergedRef = useCallback(
        (node: HTMLInputElement | null) => {
            // Update internal ref
            ;(internalRef as React.MutableRefObject<HTMLInputElement | null>).current = node

            // Update forwarded ref
            if (typeof ref === 'function') {
                ref(node)
            } else if (ref) {
                ref.current = node
            }
        },
        [ref]
    )

    useEffect(() => {
        const timeout = setTimeout(() => {
            if (autoFocus) {
                internalRef.current?.focus()
            }
        }, 1)
        return () => clearTimeout(timeout)
    }, [autoFocus])

    return (
        <div
            className={cn(
                textInputVariants({
                    variant,
                    size,
                }),
                className
            )}
        >
            <input
                ref={mergedRef}
                type={type}
                className={cn(
                    textInputVariants({ size, variant: 'invisible', hasSuffix: suffix ? true : false }),
                    'flex-1'
                )}
                {...rest}
            />
            {suffix && <div className="absolute right-0 top-0 bottom-0 flex items-center pr-[5px]">{suffix}</div>}
        </div>
    )
})

TextInputPrimitive.displayName = 'TextInputPrimitive'
