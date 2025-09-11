import { ElementRect } from '~/toolbar/types'

interface AutocaptureElementProps {
    rect?: ElementRect
    style: Record<string, any>
    onClick: (event: React.MouseEvent) => void
    onMouseOver: (event: React.MouseEvent) => void
    onMouseOut: (event: React.MouseEvent) => void
}

export function AutocaptureElement({
    rect,
    style = {},
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
}
