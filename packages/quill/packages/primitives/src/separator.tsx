import { Separator as SeparatorPrimitive } from '@base-ui/react/separator'
import * as React from 'react'

import './separator.css'
import { cn } from './lib/utils'

function Separator({ className, orientation = 'horizontal', ...props }: SeparatorPrimitive.Props): React.ReactElement {
    return (
        <SeparatorPrimitive
            data-quill
            data-slot="separator"
            orientation={orientation}
            className={cn('quill-separator shrink-0', className)}
            {...props}
        />
    )
}

export { Separator }
