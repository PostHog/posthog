import { useValues } from 'kea'

import { AutocaptureElement } from '~/toolbar/elements/AutocaptureElement'
import { HeatmapOverlayElements } from '~/toolbar/elements/HeatmapOverlayElements'
import { getBoxColors } from '~/toolbar/utils'

import { extensionContentLogic } from './extensionContentLogic'

const noop = (): void => {}

// The overlay lives in a shadow root on the customer's page without the toolbar stylesheet, so it uses inline styles.
const HINT_STYLE = {
    position: 'fixed',
    top: 12,
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: 8,
    padding: '6px 12px',
    borderRadius: 6,
    background: 'hsla(0, 0%, 9%, 0.95)',
    color: 'white',
    font: '13px/1.4 system-ui, sans-serif',
    boxShadow: 'hsla(0, 0%, 0%, 0.3) 0px 2px 8px',
} as const

export function ExtensionContentOverlay(): JSX.Element {
    const { selecting, hoverRect, confirmedRect, heatmapOverlayElements, highestClickCount } =
        useValues(extensionContentLogic)
    const highlightRect = selecting ? hoverRect : confirmedRect

    return (
        <>
            <HeatmapOverlayElements
                heatmapElements={heatmapOverlayElements}
                hoverElement={null}
                selectedElement={null}
                inspectEnabled={selecting}
                heatmapPointerEvents="none"
                highestClickCount={highestClickCount}
                selectElement={noop}
                setHoverElement={noop}
            />
            {highlightRect && (
                <AutocaptureElement
                    rect={highlightRect}
                    style={{ pointerEvents: 'none', zIndex: 6, borderRadius: 5, ...getBoxColors('blue', true) }}
                    onClick={noop}
                    onMouseOver={noop}
                    onMouseOut={noop}
                />
            )}
            {selecting && (
                // eslint-disable-next-line react/forbid-dom-props
                <div style={HINT_STYLE}>Click an element to select it. Press Esc to cancel.</div>
            )}
            {!selecting &&
                confirmedRect && (
                    // eslint-disable-next-line react/forbid-dom-props
                    <div style={HINT_STYLE}>Element selected. Open the PostHog extension to see it.</div>
                )}
        </>
    )
}
