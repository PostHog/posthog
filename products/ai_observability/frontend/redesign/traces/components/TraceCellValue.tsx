import { ReactNode } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import type { TraceCellStatus } from '../../shared/cellLoads'

const LOAD_FAILED = "Couldn't load this. Reload the list to try again."

export interface TraceCellValueProps {
    /** A value the row carries is always ready. Values read after the row pass their status. */
    status?: TraceCellStatus
    /** The skeleton's width while loading, as a Tailwind width class. */
    skeletonWidth?: string
    /** What a failed read says, where no list reload reads it again. */
    failedMessage?: string
    /** The rendered value, or null when there is none. */
    children: ReactNode
}

export function TraceCellValue({
    status = 'ready',
    skeletonWidth = 'w-16',
    failedMessage = LOAD_FAILED,
    children,
}: TraceCellValueProps): JSX.Element {
    if (status === 'loading') {
        return <LemonSkeleton className={`h-4 ${skeletonWidth}`} />
    }
    if (status === 'error') {
        return (
            <Tooltip title={failedMessage}>
                <span role="img" aria-label={failedMessage} className="inline-flex text-muted">
                    <IconWarning />
                </span>
            </Tooltip>
        )
    }
    if (children === null || children === undefined) {
        return <span className="text-muted">-</span>
    }
    return <>{children}</>
}
