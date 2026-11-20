import './input.css'

import { Input as InputPrimitive } from '@base-ui/react/input'
import * as React from 'react'

import { cn } from './lib/utils'
import { hasTooltipContent, withDisabledReason } from './with-tooltip'

// The browser ignores `readOnly` on these types, so only native `disabled` stops a change.
const READ_ONLY_IGNORED_TYPES = new Set([
    'checkbox',
    'radio',
    'file',
    'range',
    'color',
    'button',
    'submit',
    'reset',
    'image',
])

const Input = React.forwardRef<
    HTMLInputElement,
    Omit<React.ComponentProps<'input'>, 'size'> & {
        /** `sm` matches a default-size Button, for a field that shares a row with buttons. */
        size?: 'default' | 'sm'
        /** Disables the field and says why in a tooltip. Takes the place of `disabled` while set. */
        disabledReason?: React.ReactNode
    }
>(({ className, type, size = 'default', disabled, disabledReason, ...props }, ref) => {
    const hasDisabledReason = hasTooltipContent(disabledReason)
    const keepsNativeDisabled = hasDisabledReason && type !== undefined && READ_ONLY_IGNORED_TYPES.has(type)
    const usesReadOnly = hasDisabledReason && !keepsNativeDisabled

    return withDisabledReason(
        <InputPrimitive
            ref={ref}
            type={type}
            data-quill
            data-slot="input"
            data-size={size}
            className={cn('quill-input', size === 'sm' && 'quill-input--size-sm', className)}
            disabled={keepsNativeDisabled || (usesReadOnly ? undefined : disabled)}
            {...props}
            // A native disabled input ignores the pointer and leaves the tab order, which would hide its reason.
            {...(usesReadOnly && { readOnly: true, 'aria-disabled': true })}
        />,
        disabledReason,
        keepsNativeDisabled ? { target: 'inline', focusable: true } : { target: 'self' }
    )
})
Input.displayName = 'Input'

export { Input }
