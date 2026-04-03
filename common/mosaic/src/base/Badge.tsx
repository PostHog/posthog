import type { ReactElement, ReactNode } from 'react'

import { cn } from '../utils'

const variantStyles = {
    success: 'bg-success/10 text-success',
    danger: 'bg-danger/10 text-danger',
    warning: 'bg-warning/10 text-warning',
    info: 'bg-info/10 text-info',
    neutral: 'bg-bg-tertiary text-text-secondary',
} as const

const sizeStyles = {
    sm: 'px-1.5 py-0.5 text-xs',
    md: 'px-2 py-0.5 text-sm',
} as const

export interface BadgeProps {
    variant?: keyof typeof variantStyles
    size?: keyof typeof sizeStyles
    children: ReactNode
    className?: string
}

export function Badge({ variant = 'neutral', size = 'sm', children, className }: BadgeProps): ReactElement {
    return (
        <span
            className={cn(
                'inline-flex items-center rounded-md font-medium',
                variantStyles[variant],
                sizeStyles[size],
                className
            )}
        >
            {children}
        </span>
    )
}
