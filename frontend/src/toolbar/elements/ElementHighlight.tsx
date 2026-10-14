import { ElementRect } from '~/toolbar/types'

export interface ElementHighlightProps {
    rect: ElementRect
    isSelected?: boolean
}

export function ElementHighlight({ rect, isSelected }: ElementHighlightProps): JSX.Element {
    const { top, left, width, height } = rect
    const padding = 4
    const borderWidth = 2

    const color = isSelected ? '#1d4aff' : '#f97316'
    const colorLight = isSelected ? 'rgba(29, 74, 255, 0.1)' : 'rgba(249, 115, 22, 0.1)'

    return (
        <div
            className="fixed pointer-events-none"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                top: top - padding,
                left: left - padding,
                width: width + padding * 2,
                height: height + padding * 2,
                borderRadius: 6,
                border: `${borderWidth}px solid ${color}`,
                boxShadow: `0 0 8px ${color}40`,
                zIndex: 2147483015,
                background: colorLight,
            }}
        />
    )
}
