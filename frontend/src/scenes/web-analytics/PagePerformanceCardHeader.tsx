import { ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export function PagePerformanceCardHeader({
    title,
    description,
    actions,
}: {
    title: string
    /** How to read the tile, shown on hover next to the title rather than as a footer under the data. */
    description?: string
    actions?: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
            <h3 className="m-0 flex items-center gap-1 text-sm font-semibold">
                {title}
                {description ? (
                    <Tooltip title={description}>
                        <IconInfo className="text-secondary text-base shrink-0" aria-label={description} />
                    </Tooltip>
                ) : null}
            </h3>
            {actions}
        </div>
    )
}
