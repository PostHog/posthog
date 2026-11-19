import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface PartialTotalProps {
    /** Whether the value was computed from the trace's earliest steps only. */
    partial: boolean
    children: string
    className?: string
}

export function PartialTotal({ partial, children, className }: PartialTotalProps): JSX.Element {
    if (!partial) {
        return <span className={cn('whitespace-nowrap', className)}>{children}</span>
    }
    return (
        <Tooltip title="Partial. This trace has more steps than the list reads, so its tokens, errors and tools come from its earliest steps only.">
            <span className={cn('cursor-help whitespace-nowrap underline decoration-dotted', className)}>
                {children}
            </span>
        </Tooltip>
    )
}
