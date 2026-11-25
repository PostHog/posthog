import './textarea.css'

import * as React from 'react'

import { cn } from './lib/utils'
import { hasTooltipContent, withDisabledReason } from './with-tooltip'

const Textarea = React.forwardRef<
    HTMLTextAreaElement,
    React.ComponentProps<'textarea'> & {
        /** Disables the field and says why in a tooltip. Takes the place of `disabled` while set. */
        disabledReason?: React.ReactNode
    }
>(function Textarea({ className, disabled, disabledReason, ...props }, ref) {
    const hasDisabledReason = hasTooltipContent(disabledReason)

    return withDisabledReason(
        <textarea
            ref={ref}
            data-quill
            data-slot="textarea"
            className={cn('quill-textarea flex', className)}
            disabled={hasDisabledReason ? undefined : disabled}
            {...props}
            // A native disabled textarea ignores the pointer and leaves the tab order, which would hide its reason.
            {...(hasDisabledReason && { readOnly: true, 'aria-disabled': true })}
        />,
        disabledReason,
        { target: 'self' }
    )
})

export { Textarea }
