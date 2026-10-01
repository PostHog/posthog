import './SourceDragOverlay.scss'

import { useValues } from 'kea'
import { createPortal } from 'react-dom'

import { canvasSourceDragLogic } from './canvasSourceDragLogic'
import { libraryIcon } from './libraryCatalog'

// The card sits just below and right of the pointer, so it never covers the drop line.
const GHOST_OFFSET_X = 14
const GHOST_OFFSET_Y = 10

/** The card that follows the pointer while a block is dragged onto or across the canvas. */
export function SourceDragOverlay(): JSX.Element | null {
    const { ghost } = useValues(canvasSourceDragLogic)
    if (!ghost) {
        return null
    }
    const Icon = libraryIcon(ghost.blockType)
    const x = ghost.x + GHOST_OFFSET_X
    const y = ghost.y + GHOST_OFFSET_Y
    return createPortal(
        <div data-quill>
            {/* Covers the frame while dragging, so the host keeps receiving pointer events. */}
            {ghost.phase === 'drag' ? <div className="CanvasSourceDrag__shield cursor-grabbing" /> : null}
            <div
                className="CanvasSourceDrag__ghost"
                data-phase={ghost.phase}
                style={{ transform: `translate3d(${x}px, ${y}px, 0) rotate(${ghost.tilt.toFixed(2)}deg)` }}
            >
                <div className="CanvasSourceDrag__card flex w-56 items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-2.5">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-fill-hover text-foreground">
                        <Icon className="size-4" />
                    </div>
                    <div className="min-w-0">
                        <div className="truncate text-xs font-medium text-foreground">{ghost.label}</div>
                        <div className="truncate text-xs text-muted-foreground">{ghost.hint}</div>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    )
}
