import { cn } from '@posthog/quill'

import { TodaySectionResizer } from './useTodaySectionLayout'

interface TodayPaneSectionResizeHandleProps {
    label: string
    active: boolean
    resizer: TodaySectionResizer
}

export function TodayPaneSectionResizeHandle({
    label,
    active,
    resizer,
}: TodayPaneSectionResizeHandleProps): JSX.Element {
    return (
        <button
            type="button"
            className="group/resize absolute inset-x-0 -top-1 z-10 flex h-2 cursor-row-resize touch-none items-center outline-none"
            aria-label={`Resize ${label}`}
            title="Drag to resize. Double-click to reset."
            data-attr="today-section-resize"
            onPointerDown={resizer.onPointerDown}
            onPointerMove={resizer.onPointerMove}
            onPointerUp={resizer.onPointerUp}
            onPointerCancel={resizer.onPointerCancel}
            onKeyDown={resizer.onKeyDown}
            onDoubleClick={resizer.onDoubleClick}
        >
            <span
                className={cn(
                    'h-0.5 w-full rounded-full bg-primary opacity-0 transition-opacity group-hover/resize:opacity-100 group-focus-visible/resize:opacity-100',
                    active && 'opacity-100'
                )}
            />
        </button>
    )
}
