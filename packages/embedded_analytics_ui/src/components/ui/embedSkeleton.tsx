import { ReactNode } from 'react'

import { cn } from '../../utils'

function EmbedSkeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>): ReactNode {
    return <div className={cn('analytics-skeleton', className)} {...props} />
}

export { EmbedSkeleton }
