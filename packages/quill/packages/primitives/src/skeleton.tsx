import * as React from 'react'

import './skeleton.css'
import { cn } from './lib/utils'

const Skeleton = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function Skeleton(
    { className, ...props },
    ref
) {
    return <div ref={ref} data-quill data-slot="skeleton" className={cn('quill-skeleton', className)} {...props} />
})

export { Skeleton }
