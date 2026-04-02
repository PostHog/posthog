import type { HTMLAttributes, ReactElement } from 'react'

import { cn } from '../utils'

const paddingStyles = {
    none: '',
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-6',
} as const

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
    padding?: keyof typeof paddingStyles
}

export function Card({ padding = 'md', className, ...props }: CardProps): ReactElement {
    return (
        <div
            className={cn('rounded-lg border border-border-primary bg-bg-primary', paddingStyles[padding], className)}
            {...props}
        />
    )
}
