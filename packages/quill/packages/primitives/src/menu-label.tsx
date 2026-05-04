import * as React from 'react'

import { cn } from './lib/utils'
import './menu-label.css'

function MenuLabel({ className, ...props }: React.ComponentProps<'label'>): React.ReactElement {
    return <label data-quill data-slot="menu-label" className={cn('quill-menu-label', className)} {...props} />
}

export { MenuLabel }
