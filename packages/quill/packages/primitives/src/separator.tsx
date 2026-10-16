import { Separator as SeparatorPrimitive } from '@base-ui/react/separator'
import * as React from 'react'

import './separator.css'
import { cn } from './lib/utils'

const Separator = React.forwardRef<React.ComponentRef<typeof SeparatorPrimitive>, SeparatorPrimitive.Props>(
    function Separator({ className, orientation = 'horizontal', ...props }, ref) {
        return (
            <SeparatorPrimitive
                ref={ref}
                data-quill
                data-slot="separator"
                orientation={orientation}
                className={cn('quill-separator shrink-0', className)}
                {...props}
            />
        )
    }
)

export { Separator }
