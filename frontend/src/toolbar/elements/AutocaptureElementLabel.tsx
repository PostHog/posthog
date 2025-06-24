import { ElementRect } from '~/toolbar/types'
import { inBounds } from '~/toolbar/utils'

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

export function AutocaptureElementLabel({
    rect,
    style = {},
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
}
