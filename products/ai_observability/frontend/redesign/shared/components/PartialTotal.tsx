import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface PartialTotalProps {
    /** Whether the value was computed from only some of the trace's steps. */
    partial: boolean
    children: string
    className?: string
}

export function PartialTotal({ partial, children, className }: PartialTotalProps): JSX.Element {
    if (!partial) {
        return <span className={cn('whitespace-nowrap', className)}>{children}</span>
    }
    return (
        <Tooltip title="Partial. Only some of this trace's steps were read, so this value covers those steps only.">
            <span className={cn('cursor-help whitespace-nowrap underline decoration-dotted', className)}>
                {children}
            </span>
        </Tooltip>
    )
}
