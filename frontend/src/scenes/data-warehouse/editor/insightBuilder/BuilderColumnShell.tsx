import { useValues } from 'kea'
import { useRef } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { type ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

const DEFAULT_WIDTH = 240
const MIN_WIDTH = 180
const MAX_WIDTH = 420

/**
 * A builder canvas side column that collapses to a narrow icon rail and, when expanded, can be
 * width-dragged. `side` picks which edge the resize handle sits on (right for left-side columns,
 * left for the right-side Format column).
 */
export function BuilderColumnShell({
    columnKey,
    icon,
    label,
    collapsed,
    onToggle,
    side,
    children,
}: {
    columnKey: string
    icon: JSX.Element
    label: string
    collapsed: boolean
    onToggle: () => void
    side: 'left' | 'right'
    children: React.ReactNode
}): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: `sql-builder-col-${columnKey}`,
        placement: side === 'left' ? 'left' : 'right',
        persistent: true,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))
    const width = Math.min(Math.max(desiredSize || DEFAULT_WIDTH, MIN_WIDTH), MAX_WIDTH)

    if (collapsed) {
        return (
            <div
                className={cn(
                    'flex w-11 shrink-0 flex-col items-center gap-2 bg-surface-primary py-2',
                    side === 'left' ? 'border-r' : 'border-l'
                )}
                data-attr={`sql-builder-column-${columnKey}-collapsed`}
            >
                <Tooltip title={`Expand ${label}`} placement={side === 'left' ? 'right' : 'left'}>
                    <LemonButton icon={icon} size="small" type="tertiary" onClick={onToggle} />
                </Tooltip>
            </div>
        )
    }

    return (
        <div
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width }}
            className={cn(
                'relative flex shrink-0 flex-col overflow-hidden bg-surface-primary',
                side === 'left' ? 'border-r' : 'border-l'
            )}
            data-attr={`sql-builder-column-${columnKey}`}
        >
            <div className="flex shrink-0 items-center justify-between gap-1 border-b px-2 py-1">
                <span className="flex items-center gap-1.5 text-xs font-semibold uppercase text-tertiary">
                    {icon}
                    {label}
                </span>
                <LemonButton
                    icon={side === 'left' ? <IconChevronLeft /> : <IconChevronRight />}
                    size="xsmall"
                    type="tertiary"
                    onClick={onToggle}
                    tooltip={`Collapse ${label}`}
                />
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
            <Resizer {...resizerProps} />
        </div>
    )
}
