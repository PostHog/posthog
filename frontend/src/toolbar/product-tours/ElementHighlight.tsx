import { ElementRect } from '~/toolbar/types'

export interface ElementHighlightProps {
    rect: ElementRect
    isSelected?: boolean
    stepNumber?: number
}

export function ElementHighlight({ rect, isSelected, stepNumber }: ElementHighlightProps): JSX.Element {
    const { top, left, width, height } = rect
    const padding = 4
    const borderWidth = 2

    const color = isSelected ? '#1d4aff' : '#f97316'
    const colorLight = isSelected ? 'rgba(29, 74, 255, 0.1)' : 'rgba(249, 115, 22, 0.1)'

    return (
        <>
            {/* Main highlight box */}
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

            {/* Step number badge (if provided) - always PostHog blue */}
            {stepNumber !== undefined && (
                <div
                    className="fixed pointer-events-none flex items-center justify-center font-bold text-white toolbar-animate-pop"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        top: top - padding - 10,
                        left: left + width + padding - 10,
                        width: 24,
                        height: 24,
                        fontSize: 12,
                        borderRadius: '50%',
                        background: '#1d4aff',
                        boxShadow: '0 1px 4px rgba(0, 0, 0, 0.3), 0 0 0 2px white',
                        zIndex: 2147483016,
                    }}
                >
                    {stepNumber}
                </div>
            )}
        </>
    )
}
