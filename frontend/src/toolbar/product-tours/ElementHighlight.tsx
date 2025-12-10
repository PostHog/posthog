import { ElementRect } from '~/toolbar/types'

export function ElementHighlight({ rect }: { rect: ElementRect }): JSX.Element {
    const padding = 4
    const top = rect.top - padding
    const left = rect.left - padding
    const width = rect.width + padding * 2
    const height = rect.height + padding * 2

    // clip-path polygon: outer rectangle, then inner cutout (wound opposite direction)
    const clipPath = `polygon(
        evenodd,
        0 0, 100% 0, 100% 100%, 0 100%, 0 0,
        ${left}px ${top}px,
        ${left}px ${top + height}px,
        ${left + width}px ${top + height}px,
        ${left + width}px ${top}px,
        ${left}px ${top}px
    )`

    return (
        <>
            {/* Dim overlay with cutout */}
            <div
                className="fixed inset-0 pointer-events-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    backgroundColor: 'rgba(0, 0, 0, 0.5)',
                    clipPath,
                }}
            />
            {/* Border around element */}
            <div
                className="fixed pointer-events-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    top,
                    left,
                    width,
                    height,
                    borderRadius: 4,
                    border: '2px solid #1d4aff',
                    boxShadow: '0 0 0 4px rgba(29, 74, 255, 0.2)',
                }}
            />
        </>
    )
}
