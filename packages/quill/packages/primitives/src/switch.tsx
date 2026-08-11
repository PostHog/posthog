import { Switch as SwitchPrimitive } from '@base-ui/react/switch'
import * as React from 'react'

import './switch.css'
import { cn } from './lib/utils'

/**
 * Represents the switch itself.
 * Renders a `<span>` element and a hidden `<input>` beside.
 *
 * Documentation: [Base UI Switch](https://base-ui.com/react/components/switch)
 *
 * @baseui Switch.Root
 */
function Switch({
    className,
    size = 'default',
    ...props
}: SwitchPrimitive.Root.Props & {
    size?: 'sm' | 'default'
}): React.ReactElement {
    return (
        <SwitchPrimitive.Root
            data-quill
            data-slot="switch"
            data-size={size}
            className={cn('quill-switch peer group/switch inline-flex shrink-0 items-center', className)}
            {...props}
        >
            <SwitchPrimitive.Thumb data-slot="switch-thumb" className="quill-switch__thumb" />
        </SwitchPrimitive.Root>
    )
}

export { Switch }
