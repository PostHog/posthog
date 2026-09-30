import { cn } from 'lib/utils/css-classes'

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
            className={cn('TodayPaneSection__resize', active && 'TodayPaneSection__resize--active')}
            aria-label={`Resize ${label}`}
            title="Drag to resize. Double-click to reset."
            data-attr="today-section-resize"
            onPointerDown={resizer.onPointerDown}
            onPointerMove={resizer.onPointerMove}
            onPointerUp={resizer.onPointerUp}
            onPointerCancel={resizer.onPointerUp}
            onKeyDown={resizer.onKeyDown}
            onDoubleClick={resizer.onDoubleClick}
        >
            <span className="TodayPaneSection__resize-line" />
        </button>
    )
}
