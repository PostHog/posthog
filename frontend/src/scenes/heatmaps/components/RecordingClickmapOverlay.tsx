import { useValues } from 'kea'
import React, { useEffect, useRef } from 'react'

import { humanFriendlyLargeNumber } from 'lib/utils'

import { recordingClickmapLogic } from './recordingClickmapLogic'

function useSnapshotScrollTransform(
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
): React.RefObject<HTMLDivElement> {
    const innerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        let rafId: number | undefined
        let lastX = -1
        let lastY = -1

        const onFrame = (): void => {
            const snapshotWindow = iframeRef?.current?.contentWindow
            const scrollX = snapshotWindow?.scrollX ?? 0
            const scrollY = snapshotWindow?.scrollY ?? 0
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
    }, [iframeRef])

    return innerRef
}

export function RecordingClickmapOverlay({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = recordingClickmapLogic({ iframeRef })
    const { clickmapEnabled, clickmapBoxes, highestClickCount } = useValues(logic)
    const innerRef = useSnapshotScrollTransform(iframeRef)

    if (!clickmapEnabled || clickmapBoxes.length === 0) {
        return null
    }

    return (
        <div className="absolute inset-0 overflow-hidden pointer-events-none z-10">
            <div ref={innerRef} className="absolute inset-0">
                {clickmapBoxes.map((box, index) => (
                    <div
                        key={index}
                        className="absolute rounded-sm border border-danger"
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
                    >
                        <div className="absolute -top-2 -left-2 rounded-full bg-danger text-white text-xs px-1 whitespace-nowrap">
                            {humanFriendlyLargeNumber(box.count)}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}
