import { Separator as SeparatorPrimitive } from '@base-ui/react/separator'
import * as React from 'react'

import './separator.css'
import { cn } from './lib/utils'

/**
 * A separator element accessible to screen readers.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Separator](https://base-ui.com/react/components/separator)
 *
 * @baseui Separator
 */
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
