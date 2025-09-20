import './TextInputPrimitive.css'

import { type VariantProps, cva } from 'cva'
import { forwardRef, useCallback, useEffect, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

export const textInputVariants = cva({
    base: 'text-input-primitive w-full rounded border border-primary p-2 text-sm outline-none focus-visible:border-secondary',
    variants: {
        variant: {
            default: 'border-primary bg-surface-primary hover:border-secondary',
        },
        size: {
            sm: 'text-input-primitive--height-sm',
            default: 'text-input-primitive--height-base',
            lg: 'text-input-primitive--height-lg',
            auto: '',
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
})

export type TextInputBaseProps = {
    onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void
    autoFocus?: boolean
    dataAttr?: string
    className?: string
} & VariantProps<typeof textInputVariants>

export interface TextInputPrimitiveProps
    extends TextInputBaseProps,
        Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'> {}

export const TextInputPrimitive = forwardRef<HTMLInputElement, TextInputPrimitiveProps>((props, ref) => {
    const { autoFocus, variant, size = 'default', type = 'text', className, ...rest } = props

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
        <input
            ref={mergedRef}
            type={type}
            className={cn(
                textInputVariants({
                    variant,
                    size,
                }),
                className
            )}
            {...rest}
        />
    )
})

TextInputPrimitive.displayName = 'TextInputPrimitive'
