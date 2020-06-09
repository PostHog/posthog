import React from 'react'
import { useActions, useValues } from 'kea'
import { heatmapLogic } from '~/toolbar/shared/heatmapLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { FocusRect } from '~/toolbar/shared/FocusRect'

export function Heatmap({ apiURL, temporaryToken }) {
    const { href } = useValues(currentPageLogic)
    const logic = heatmapLogic({ apiURL, temporaryToken, current_url: href })
    const { countedElementsWithRects, highlightedElement, showElementFinder } = useValues(logic)
    const { highlightElement } = useActions(logic)
    const { zoom, padding } = useValues(dockLogic)

    const highlightedRect = highlightedElement ? highlightedElement.getBoundingClientRect() : null

    return (
        <div
            id="posthog-heatmap"
            style={{
                width: '100%',
                height: '100%',
                position: 'absolute',
                top: 0,
                left: 0,
                zIndex: '2147483620',
            }}
        >
            {highlightedRect && showElementFinder ? <FocusRect rect={highlightedRect} /> : null}
            {countedElementsWithRects.map(({ rect, element }, index) => {
                return (
                    <React.Fragment key={index}>
                        <div
                            style={{
                                position: 'absolute',
                                top: `${(rect.top - padding) / zoom}px`,
                                left: `${(rect.left - padding) / zoom}px`,
                                width: `${(rect.right - rect.left) / zoom}px`,
                                height: `${(rect.bottom - rect.top) / zoom}px`,
                                zIndex: 1,
                                opacity: highlightedElement && highlightedElement !== element ? 0.4 : 1,
                                transition: 'opacity 0.2s',
                                cursor: 'pointer',
                                backgroundBlendMode: 'multiply',
                                // green
                                // background: 'rgba(76, 174, 79, 0.3)',
                                // boxShadow: 'rgba(53, 95, 54, 0.7) 0px 3px 10px 2px',
                                // // red
                                background: 'hsla(4, 90%, 58%, 0.4)',
                                boxShadow: 'hsla(4, 90%, 27%, 0.8) 0px 3px 10px 2px',
                            }}
                            onMouseEnter={() => highlightElement(element)}
                            onMouseLeave={() => highlightElement(null)}
                        />
                        <div
                            style={{
                                position: 'absolute',
                                zIndex: 2,
                                top: `${(rect.top - padding - 7) / zoom}px`,
                                left: `${(rect.left + rect.width - padding - 14) / zoom}px`,
                                lineHeight: '14px',
                                padding: '1px 4px',
                                opacity: highlightedElement && highlightedElement !== element ? 0.4 : 1,
                                transition: 'opacity 0.2s',
                                color: 'hsla(54, 20%, 12%, 1)',
                                background: '#FFEB3B',
                                boxShadow: 'hsla(54, 100%, 32%, 1) 0px 1px 5px 1px',
                                fontSize: 16,
                                fontWeight: 'bold',
                                fontFamily: 'monospace',
                                pointerEvents: 'none',
                            }}
                        >
                            {index + 1}
                        </div>
                    </React.Fragment>
                )
            })}
        </div>
    )
}
