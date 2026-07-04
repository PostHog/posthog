import { useActions, useValues } from 'kea'
import React, { useEffect, useRef } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { ElementClickStats } from 'lib/components/heatmaps/ElementClickStats'
import { Popover } from 'lib/lemon-ui/Popover'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { ClickmapBox, recordingClickmapLogic } from './recordingClickmapLogic'

function useSnapshotScrollTransform(
    enabled: boolean,
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
): React.RefObject<HTMLDivElement> {
    const innerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (!enabled) {
            return
        }

        let rafId: number | undefined
        let lastX = -1
        let lastY = -1

        // polling like useScrollSync does, because a scroll listener would need
        // re-binding every time the srcDoc document is replaced
        const onFrame = (): void => {
            let scrollX = 0
            let scrollY = 0
            try {
                const snapshotWindow = iframeRef?.current?.contentWindow
                scrollX = snapshotWindow?.scrollX ?? 0
                scrollY = snapshotWindow?.scrollY ?? 0
            } catch {
                // the frame navigated cross-origin; keep the overlay where it was
            }
            if (scrollX !== lastX || scrollY !== lastY) {
                lastX = scrollX
                lastY = scrollY
                if (innerRef.current) {
                    innerRef.current.style.transform = `translate(${-scrollX}px, ${-scrollY}px)`
                }
            }
            rafId = requestAnimationFrame(onFrame)
        }

        rafId = requestAnimationFrame(onFrame)
        return () => {
            if (rafId !== undefined) {
                cancelAnimationFrame(rafId)
            }
        }
    }, [enabled, iframeRef])

    return innerRef
}

function ClickmapBoxInfo({
    box,
    rank,
    totalCount,
}: {
    box: ClickmapBox
    rank: number
    totalCount: number
}): JSX.Element {
    return (
        <div className="deprecated-space-y-1 max-w-100">
            {box.label ? <div className="font-semibold">{box.label}</div> : null}
            <div className="font-mono text-xs text-muted-alt">{box.selector}</div>
            <ElementClickStats
                count={box.count}
                totalCount={totalCount}
                rank={rank}
                clickCount={box.clickCount}
                rageclickCount={box.rageclickCount}
                deadclickCount={box.deadclickCount}
            />
        </div>
    )
}

export function RecordingClickmapOverlay({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = recordingClickmapLogic({ iframeRef })
    const { clickmapActive, clickmapBoxes, highestClickCount, selectedBoxKey } = useValues(logic)
    const { selectClickmapBox, setHeatmapTooltipSuppressed } = useActions(logic)
    const showClickmap = clickmapActive && clickmapBoxes.length > 0
    const innerRef = useSnapshotScrollTransform(showClickmap, iframeRef)

    if (!showClickmap) {
        return null
    }

    const totalCount = clickmapBoxes.reduce((sum, box) => sum + box.count, 0)

    return (
        <div className="absolute inset-0 overflow-hidden pointer-events-none z-10" data-attr="heatmap-clickmap-overlay">
            <div ref={innerRef} className="absolute inset-0">
                {clickmapBoxes.map((box, index) => {
                    const key = `${box.top}:${box.left}:${index}`
                    const isSelected = key === selectedBoxKey
                    const boxElement = (
                        <div
                            className={`absolute rounded-sm border border-danger pointer-events-auto cursor-pointer ${
                                isSelected ? 'border-2' : 'hover:border-2'
                            }`}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                top: box.top,
                                left: box.left,
                                width: box.width,
                                height: box.height,
                                backgroundColor: `rgba(245, 78, 0, ${
                                    0.1 + 0.4 * (highestClickCount ? box.count / highestClickCount : 0)
                                })`,
                            }}
                            onClick={() => selectClickmapBox(isSelected ? null : key)}
                            onMouseEnter={() => setHeatmapTooltipSuppressed(true)}
                            onMouseLeave={() => setHeatmapTooltipSuppressed(false)}
                            onWheel={(e) => {
                                // the boxes intercept pointer events, so hand scrolling
                                // back to the snapshot document underneath
                                iframeRef?.current?.contentWindow?.scrollBy(e.deltaX, e.deltaY)
                            }}
                        >
                            <div className="absolute -top-2 -left-2 rounded-full bg-danger text-white text-xs px-1 whitespace-nowrap">
                                {humanFriendlyLargeNumber(box.count)}
                            </div>
                        </div>
                    )

                    return isSelected ? (
                        <Popover
                            key={key}
                            visible
                            onClickOutside={() => selectClickmapBox(null)}
                            placement="right"
                            overlay={
                                <div className="p-2">
                                    <ClickmapBoxInfo box={box} rank={index + 1} totalCount={totalCount} />
                                </div>
                            }
                        >
                            {boxElement}
                        </Popover>
                    ) : (
                        <Tooltip
                            key={key}
                            title={<ClickmapBoxInfo box={box} rank={index + 1} totalCount={totalCount} />}
                        >
                            {boxElement}
                        </Tooltip>
                    )
                })}
            </div>
        </div>
    )
}
