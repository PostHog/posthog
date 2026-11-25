import './switch.css'

import { Switch as SwitchPrimitive } from '@base-ui/react/switch'
import * as React from 'react'

import { useDisabledControl } from './disabled-reason'
import { cn } from './lib/utils'

const Switch = React.forwardRef<
    React.ComponentRef<typeof SwitchPrimitive.Root>,
    Omit<SwitchPrimitive.Root.Props, 'children'> & {
        size?: 'sm' | 'default'
        /** Disables the switch and says why in a tooltip. */
        disabledReason?: React.ReactNode
        /** The label. It wraps the switch, so the label also toggles it and shows the disabled reason. */
        children?: React.ReactNode
    }
>(function Switch({ className, size = 'default', disabled, disabledReason, children, ...props }, ref) {
    const { rootProps, wrap } = useDisabledControl({
        disabled,
        disabledReason,
        label: children,
        ariaDescribedBy: props['aria-describedby'],
    })
    return wrap(
        <SwitchPrimitive.Root
            ref={ref}
            data-quill
            data-slot="switch"
            data-size={size}
            className={cn('quill-switch peer group/switch inline-flex shrink-0 items-center', className)}
            {...props}
            {...rootProps}
        >
            <SwitchPrimitive.Thumb data-slot="switch-thumb" className="quill-switch__thumb" />
        </SwitchPrimitive.Root>
    )
})

export { Switch }
