import type { ReactElement } from 'react'

import { emptyStateIllustration, type EmptyStateIllustrationType } from '../illustrations/emptyStateIllustrations'
import { cn } from '../utils'

export type { EmptyStateIllustrationType }

export interface EmptyStateProps {
    title?: string
    description?: string
    icon?: EmptyStateIllustrationType
    className?: string
}

export function EmptyState({ title, description, icon, className }: EmptyStateProps): ReactElement {
    return (
        <div className={cn('flex flex-col items-center justify-center py-10 px-4 gap-2', className)}>
            {icon && emptyStateIllustration(icon)}
            {title && <span className="text-sm font-medium text-text-primary">{title}</span>}
            {description && <span className="text-sm text-text-secondary text-center">{description}</span>}
        </div>
    )
}
