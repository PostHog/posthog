import { memo } from 'react'

import { objectsEqual } from 'lib/utils'

import { ElementRect } from '~/toolbar/core/types'
import { EMPTY_STYLE, rectEqual } from '~/toolbar/utils'

interface AutocaptureElementProps {
    rect?: ElementRect
    style: Record<string, any>
    onClick: (event: React.MouseEvent) => void
    onMouseOver: (event: React.MouseEvent) => void
    onMouseOut: (event: React.MouseEvent) => void
}

export const AutocaptureElement = memo(
    function AutocaptureElement({
        rect,
        style = EMPTY_STYLE,
        onClick,
        onMouseOver,
        onMouseOut,
    }: AutocaptureElementProps): JSX.Element | null {
        if (!rect) {
            return null
        }
        return (
            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'absolute',
                    top: `${rect.top + window.pageYOffset}px`,
                    left: `${rect.left + window.pageXOffset}px`,
                    width: `${rect.right - rect.left}px`,
                    height: `${rect.bottom - rect.top}px`,
                    ...style,
                }}
                onClick={onClick}
                onMouseOver={onMouseOver}
                onMouseOut={onMouseOut}
            />
        )
    },
    // Handlers are intentionally excluded: the sole caller (Elements.tsx) closes over
    // stable kea actions (selectElement, setHoverElement) and per-element refs that
    // don't change for a given key, so comparing them would only defeat memoization.
    (prev, next) => rectEqual(prev.rect, next.rect) && objectsEqual(prev.style, next.style)
)
