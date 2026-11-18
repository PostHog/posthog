import './input.css'

import { Input as InputPrimitive } from '@base-ui/react/input'
import * as React from 'react'

import { cn } from './lib/utils'
import { hasTooltipContent, withTooltip } from './with-tooltip'

const Input = React.forwardRef<
    HTMLInputElement,
    Omit<React.ComponentProps<'input'>, 'size'> & {
        /** `sm` matches a default-size Button, for a field that shares a row with buttons. */
        size?: 'default' | 'sm'
        /**
         * Disables the field and says why in a tooltip. The field turns read-only and stays hoverable and
         * focusable, so the reason is reachable. Takes the place of `disabled` while set.
         */
        disabledReason?: React.ReactNode
    }
>(({ className, type, size = 'default', disabled, disabledReason, ...props }, ref) => {
    const hasDisabledReason = hasTooltipContent(disabledReason)

    return withTooltip(
        <InputPrimitive
            ref={ref}
            type={type}
            data-quill
            data-slot="input"
            data-size={size}
            className={cn('quill-input', size === 'sm' && 'quill-input--size-sm', className)}
            disabled={hasDisabledReason ? undefined : disabled}
            {...props}
            // A native disabled input ignores the pointer and leaves the tab order, which would hide its reason.
            {...(hasDisabledReason && { readOnly: true, 'aria-disabled': true })}
        />,
        disabledReason,
        { target: 'self' }
    )
})
Input.displayName = 'Input'

export { Input }
