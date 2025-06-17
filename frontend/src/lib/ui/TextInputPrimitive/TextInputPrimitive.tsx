import { cva, type VariantProps } from 'cva'
import { cn } from 'lib/utils/css-classes'
import { forwardRef, useCallback, useEffect, useRef } from 'react'

const textInputVariants = cva({
    base: 'w-full rounded border border-primary p-2 text-sm outline-none focus-visible:border-secondary',
    variants: {
        variant: {
            default: 'border-primary bg-surface-primary hover:border-tertiary',
        },
        size: {
            default: 'h-[2rem]',
            sm: 'h-8 px-2',
            lg: 'h-12 px-4',
        },
    },
    defaultVariants: {
        variant: 'default',
        size: 'default',
    },
})

type TextInputBaseProps = {
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
