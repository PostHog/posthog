import { memo } from 'react'

import { objectsEqual } from 'lib/utils'

import { ElementRect } from '~/toolbar/core/types'
import { EMPTY_STYLE, inBounds, rectEqual } from '~/toolbar/utils'

const heatmapLabelStyle = {
    lineHeight: '14px',
    padding: '1px 4px',
    color: 'hsla(54, 20%, 12%, 1)',
    background: '#FFEB3B',
    boxShadow: 'hsla(54, 100%, 32%, 1) 0px 1px 5px 1px',
    fontSize: 16,
    fontWeight: 'bold' as const,
    fontFamily: '"Emoji Flags Polyfill", monospace',
}

interface AutocaptureElementLabelProps extends React.PropsWithoutRef<JSX.IntrinsicElements['div']> {
    rect?: ElementRect
    align?: 'left' | 'right'
}

export const AutocaptureElementLabel = memo(
    function AutocaptureElementLabel({
        rect,
        style = EMPTY_STYLE,
        align = 'right',
        children,
        ...props
    }: AutocaptureElementLabelProps): JSX.Element | null {
        if (!rect) {
            return null
        }

        const width = typeof children === 'string' ? children.length * 10 + 4 : 14

        return (
            <div
                className="absolute"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    top: `${inBounds(
                        window.pageYOffset - 1,
                        rect.top - 7 + window.pageYOffset,
                        window.pageYOffset + window.innerHeight - 14
                    )}px`,
                    left: `${inBounds(
                        window.pageXOffset,
                        rect.left + (align === 'left' ? 10 : rect.width) - width + window.pageXOffset,
                        window.pageXOffset + window.innerWidth - 14
                    )}px`,
                    ...heatmapLabelStyle,
                    ...style,
                }}
                {...props}
            >
                {children}
            </div>
        )
    },
    // Handlers are intentionally excluded: the sole caller (Elements.tsx) closes over
    // stable kea actions (selectElement, setHoverElement) and per-element refs that
    // don't change for a given key, so comparing them would only defeat memoization.
    (prev, next) =>
        rectEqual(prev.rect, next.rect) &&
        objectsEqual(prev.style ?? EMPTY_STYLE, next.style ?? EMPTY_STYLE) &&
        prev.align === next.align &&
        prev.children === next.children
)
