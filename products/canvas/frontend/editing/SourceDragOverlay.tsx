import './SourceDragOverlay.scss'

import { useValues } from 'kea'
import { createPortal } from 'react-dom'

import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

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
                <Item variant="outline" size="xs" className="CanvasSourceDrag__card w-56 bg-card shadow-lg">
                    <ItemMedia variant="icon" aria-hidden>
                        <Icon />
                    </ItemMedia>
                    <ItemContent className="min-w-0">
                        <ItemTitle className="truncate">{ghost.label}</ItemTitle>
                        <ItemDescription className="truncate">{ghost.hint}</ItemDescription>
                    </ItemContent>
                </Item>
            </div>
        </div>,
        document.body
    )
}
