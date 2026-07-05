import { useActions, useValues } from 'kea'
import React, { useEffect, useMemo, useRef } from 'react'

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

// pixel-equivalent heights for non-pixel wheel deltaMode values
const WHEEL_LINE_HEIGHT_PX = 20
const WHEEL_PAGE_HEIGHT_PX = 400

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
    const overlayRef = useRef<HTMLDivElement>(null)

    // render smaller boxes on top so high-count nested elements stay reachable
    const renderOrder = useMemo(
        () =>
            clickmapBoxes
                .map((box, i) => ({ box, i }))
                .sort((a, b) => b.box.width * b.box.height - a.box.width * a.box.height),
        [clickmapBoxes]
    )

    useEffect(() => {
        const el = overlayRef.current
        if (!el || !showClickmap) {
            return
        }
        // React attaches wheel as a passive root listener, so synthetic stopPropagation()
        // cannot prevent the native scroll of the outer overflow-auto container, and
        // calling preventDefault() on a passive listener throws. A single non-passive
        // listener on the overlay itself lets us do both: stop the outer scroll and
        // forward scaled deltas into the snapshot iframe underneath.
        // The overlay div is pointer-events-none, but wheel events from the
        // pointer-events-auto boxes bubble through it natively, so this fires.
        const handler = (e: WheelEvent): void => {
            e.preventDefault()
            const scale = e.deltaMode === 2 ? WHEEL_PAGE_HEIGHT_PX : e.deltaMode === 1 ? WHEEL_LINE_HEIGHT_PX : 1
            try {
                iframeRef?.current?.contentWindow?.scrollBy(e.deltaX * scale, e.deltaY * scale)
            } catch {
                // cross-origin frame; ignore
            }
        }
        el.addEventListener('wheel', handler, { passive: false })
        return () => el.removeEventListener('wheel', handler)
    }, [showClickmap, iframeRef])

    if (!showClickmap) {
        return null
    }

    return (
        <div
            ref={overlayRef}
            className="absolute inset-0 overflow-hidden pointer-events-none z-10"
            data-attr="heatmap-clickmap-overlay"
        >
            <div ref={innerRef} className="absolute inset-0">
                {renderOrder.map(({ box, i: originalIndex }) => {
                    const key = String(originalIndex)
                    const isSelected = key === selectedBoxKey
                    // the boxes intercept pointer events so wheel events from within them
                    // bubble up to the overlay's non-passive listener above
                    const boxElement = (
                        <div
                            data-attr="clickmap-box"
                            role="button"
                            tabIndex={0}
                            aria-label={box.label || box.displaySelector}
                            className={`absolute rounded-sm border border-danger pointer-events-auto cursor-pointer ${
                                isSelected ? 'border-2' : 'hover:border-2 focus-visible:border-2'
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
