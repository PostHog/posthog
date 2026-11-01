import { ReactNode } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface AICreditsTileProps {
    label: string
    /** Null while the figure loads. */
    value: string | null
    valueClassName?: string
    /** Sits on the value's baseline, such as "of $500 limit". */
    suffix?: ReactNode
    children?: ReactNode
    footer: ReactNode
    footerClassName?: string
}

export function AICreditsTile({
    label,
    value,
    valueClassName,
    suffix,
    children,
    footer,
    footerClassName,
}: AICreditsTileProps): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col rounded border bg-surface-primary">
            <div className="flex flex-1 flex-col gap-1.5 px-5 pt-5 pb-4">
                <span className="text-sm text-secondary">{label}</span>
                {value === null ? (
                    <LemonSkeleton className="h-9 w-32" />
                ) : (
                    <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className={cn('text-3xl font-bold tracking-tight', valueClassName)}>{value}</span>
                        {suffix && <span className="text-sm text-secondary">{suffix}</span>}
                    </div>
                )}
                {children}
            </div>
            <div className={cn('flex items-center gap-3 rounded-b border-t px-5 py-4', footerClassName)}>{footer}</div>
        </div>
    )
}
