import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'

import { IconDrag } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

const MetricDragHandle = ({
    listeners,
    attributes,
    setActivatorNodeRef,
    metricName,
}: {
    listeners: DraggableSyntheticListeners | undefined
    attributes: Record<string, any>
    setActivatorNodeRef: (element: HTMLElement | null) => void
    metricName: string
}): JSX.Element => (
    <Tooltip title="Drag to reorder metrics">
        <button
            type="button"
            ref={setActivatorNodeRef}
            // The IconDrag glyph only fills the middle of its viewBox, so without the negative
            // margin the visible dots sit much closer to the title than to the cell border.
            className="touch-none cursor-grab active:cursor-grabbing text-muted hover:text-default transition-colors border-none bg-transparent p-0 flex-shrink-0 -ml-2"
            aria-label={`Reorder ${metricName}`}
            {...listeners}
            {...attributes}
            data-attr="experiment-metric-drag-handle"
        >
            <IconDrag className="text-base" />
        </button>
    </Tooltip>
)

/**
 * A metric spans several `<tr>`s (baseline, one per variant, optional breakdown rows), so the
 * sortable unit has to be a `<tbody>` — a table may hold many of them.
 */
export function SortableMetricRowGroup({
    uuid,
    metricName,
    disabled,
    isLastMetric,
    children,
}: {
    uuid: string
    metricName: string
    disabled: boolean
    isLastMetric: boolean
    children: (dragHandle: JSX.Element | null) => JSX.Element
}): JSX.Element {
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
        id: uuid,
        disabled,
    })

    return (
        <tbody
            ref={disabled ? undefined : setNodeRef}
            style={{
                transform: CSS.Transform.toString(transform),
                transition: isDragging ? 'none' : transition,
                position: isDragging ? 'relative' : undefined,
                // Stays under the sticky header, which sits at z-10.
                zIndex: isDragging ? 2 : undefined,
                // The dragged group overlaps its neighbours, so the shadow makes it read as
                // lifted above them rather than merged into them.
                boxShadow: isDragging ? 'var(--shadow-elevation-3000)' : undefined,
            }}
            // Scoped here rather than on the rows: with one tbody per metric, a row-level
            // `:last-child` would strip the border between every metric, not just the final one.
            className={clsx(isLastMetric && '[&>tr:last-child>td]:border-b-0')}
        >
            {children(
                disabled ? null : (
                    <MetricDragHandle
                        listeners={listeners}
                        attributes={attributes}
                        setActivatorNodeRef={setActivatorNodeRef}
                        metricName={metricName}
                    />
                )
            )}
        </tbody>
    )
}
