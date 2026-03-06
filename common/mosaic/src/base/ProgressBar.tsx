import type { ReactElement } from 'react'

import { cn } from '../utils'

export interface ProgressBarProps {
    value: number
    max?: number
    variant?: 'info' | 'success' | 'warning' | 'danger'
    size?: 'sm' | 'md'
    showLabel?: boolean
    className?: string
}

const variantClasses: Record<string, string> = {
    info: 'bg-info',
    success: 'bg-success',
    warning: 'bg-warning',
    danger: 'bg-danger',
}

export function ProgressBar({
    value,
    max = 100,
    variant = 'info',
    size = 'md',
    showLabel = false,
    className,
}: ProgressBarProps): ReactElement {
    const percentage = max > 0 ? Math.min(Math.max((value / max) * 100, 0), 100) : 0

    return (
        <div className={cn('flex items-center gap-2', className)}>
            <div
                className={cn(
                    'flex-1 rounded-full bg-[var(--color-border-primary)]',
                    size === 'sm' ? 'h-1.5' : 'h-2.5'
                )}
            >
                <div
                    className={cn('h-full rounded-full transition-all', variantClasses[variant])}
                    style={{ width: `${percentage}%` }}
                />
            </div>
            {showLabel && <span className="text-xs text-text-secondary tabular-nums">{Math.round(percentage)}%</span>}
        </div>
    )
}
