import { Switch as SwitchPrimitive } from '@base-ui/react/switch'
import * as React from 'react'

import './switch.css'
import { cn } from './lib/utils'
import { hasTooltipContent, withTooltip } from './with-tooltip'

const Switch = React.forwardRef<
    React.ComponentRef<typeof SwitchPrimitive.Root>,
    SwitchPrimitive.Root.Props & {
        size?: 'sm' | 'default'
        /** Disables the switch and says why in a tooltip. */
        disabledReason?: React.ReactNode
    }
>(function Switch({ className, size = 'default', disabled, disabledReason, ...props }, ref) {
    return withTooltip(
        <SwitchPrimitive.Root
            ref={ref}
            data-quill
            data-slot="switch"
            data-size={size}
            disabled={disabled || hasTooltipContent(disabledReason)}
            className={cn('quill-switch peer group/switch inline-flex shrink-0 items-center', className)}
            {...props}
        >
            <SwitchPrimitive.Thumb data-slot="switch-thumb" className="quill-switch__thumb" />
        </SwitchPrimitive.Root>,
        disabledReason,
        { target: 'inline', focusable: hasTooltipContent(disabledReason) }
    )
})

export { Switch }
