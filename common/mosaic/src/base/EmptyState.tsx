import type { ReactElement } from 'react'

import { cn } from '../utils'

export interface EmptyStateProps {
    title: string
    description?: string
    className?: string
}

export function EmptyState({ title, description, className }: EmptyStateProps): ReactElement {
    return (
        <div className={cn('flex flex-col items-center justify-center py-12 gap-2', className)}>
            <span className="text-sm font-medium text-text-primary">{title}</span>
            {description && <span className="text-xs text-text-secondary text-center">{description}</span>}
        </div>
    )
}
