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
        <div className="flex flex-col gap-1 max-w-100">
            {box.label ? <div className="font-semibold">{box.label}</div> : null}
            <div className="font-mono text-xs text-muted-alt break-all">{box.displaySelector}</div>
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
    const { clickmapActive, clickmapBoxes, highestClickCount, selectedBoxKey, totalClickCount } = useValues(logic)
    const { selectClickmapBox, setHoveredBoxKey } = useActions(logic)
    const showClickmap = clickmapActive && clickmapBoxes.length > 0
    const innerRef = useSnapshotScrollTransform(showClickmap, iframeRef)

    if (!showClickmap) {
        return null
    }

    // render smaller boxes on top so high-count nested elements stay reachable
    const renderOrder = [...clickmapBoxes].sort((a, b) => b.width * b.height - a.width * a.height)

    return (
        <div className="absolute inset-0 overflow-hidden pointer-events-none z-10" data-attr="heatmap-clickmap-overlay">
            <div ref={innerRef} className="absolute inset-0">
                {renderOrder.map((box) => {
                    const originalIndex = clickmapBoxes.indexOf(box)
                    const key = `${box.top}:${box.left}:${originalIndex}`
                    const isSelected = key === selectedBoxKey
                    const boxElement = (
                        <div
                            data-attr="clickmap-box"
                            role="button"
                            tabIndex={0}
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
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault()
                                    selectClickmapBox(isSelected ? null : key)
                                }
                            }}
                            onMouseEnter={() => setHoveredBoxKey(key)}
                            onMouseLeave={() => setHoveredBoxKey(null)}
                            onWheel={(e) => {
                                // the boxes intercept pointer events, so hand scrolling
                                // back to the snapshot document underneath
                                e.stopPropagation()
                                // scale line-mode (deltaMode=1) and page-mode (deltaMode=2) to pixels
                                const scale = e.deltaMode === 2 ? 400 : e.deltaMode === 1 ? 20 : 1
                                try {
                                    iframeRef?.current?.contentWindow?.scrollBy(e.deltaX * scale, e.deltaY * scale)
                                } catch {
                                    // cross-origin frame; ignore
                                }
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
                                    <ClickmapBoxInfo box={box} rank={originalIndex + 1} totalCount={totalClickCount} />
                                </div>
                            }
                        >
                            {boxElement}
                        </Popover>
                    ) : (
                        <Tooltip
                            key={key}
                            title={<ClickmapBoxInfo box={box} rank={originalIndex + 1} totalCount={totalClickCount} />}
                        >
                            {boxElement}
                        </Tooltip>
                    )
                })}
            </div>
        </div>
    )
}
