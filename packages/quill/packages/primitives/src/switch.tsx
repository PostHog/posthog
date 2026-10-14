import { Switch as SwitchPrimitive } from '@base-ui/react/switch'
import * as React from 'react'

import './switch.css'
import { cn } from './lib/utils'

const Switch = React.forwardRef<
    React.ComponentRef<typeof SwitchPrimitive.Root>,
    SwitchPrimitive.Root.Props & {
        size?: 'sm' | 'default'
    }
>(function Switch({ className, size = 'default', ...props }, ref) {
    return (
        <SwitchPrimitive.Root
            ref={ref}
            data-quill
            data-slot="switch"
            data-size={size}
            className={cn('quill-switch peer group/switch inline-flex shrink-0 items-center', className)}
            {...props}
        >
            <SwitchPrimitive.Thumb data-slot="switch-thumb" className="quill-switch__thumb" />
        </SwitchPrimitive.Root>
    )
})

export { Switch }
