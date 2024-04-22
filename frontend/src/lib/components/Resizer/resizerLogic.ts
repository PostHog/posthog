import { actions, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import type { resizerLogicType } from './resizerLogicType'

export type ResizerEvent = {
    desiredSize: number
}

export type ResizerLogicProps = {
    logicKey: string
    persistent?: boolean
    placement: 'left' | 'right' | 'top' | 'bottom'
    containerRef: React.RefObject<HTMLDivElement>
    /** At what size, should this rather be considered a "close" event */
    closeThreshold?: number
    /** Fired when the "closeThreshold" is crossed */
    onToggleClosed?: (closed: boolean) => void
    onDoubleClick?: () => void
}

const removeAllListeners = (cache: Record<string, any>): void => {
    if (cache.onMouseMove) {
        document.removeEventListener('mousemove', cache.onMouseMove)
    }
    if (cache.onMouseUp) {
        document.removeEventListener('mouseup', cache.onMouseUp)
    }
}

export const resizerLogic = kea<resizerLogicType>([
    props({} as ResizerLogicProps),
    key((props) => props.logicKey),
    path((key) => ['components', 'resizer', 'resizerLogic', key]),
    actions({
        beginResize: (startXOrY: number) => ({ startXOrY }),
        endResize: true,
        setResizingSize: (size: number | null) => ({ size }),
        setDesiredSize: (size: number | null) => ({ size }),
        resetDesiredSize: true,
    }),
    reducers(({ props }) => ({
        isResizeInProgress: [
            false,
            {
                beginResize: () => true,
                endResize: () => false,
            },
        ],
        size: [
            null as number | null,
            { persist: props.persistent },
            {
                setDesiredSize: (_, { size }) => size,
                resetDesiredSize: () => null,
            },
        ],
        resizingSize: [
            null as number | null,
            {
                setResizingSize: (_, { size }) => size,
                beginResize: () => null,
                endResize: () => null,
            },
        ],
    })),
    selectors({
        desiredSize: [
            (s) => [s.size, s.resizingSize, s.isResizeInProgress],
            (size, resizingSize, isResizeInProgress) => {
                return isResizeInProgress ? resizingSize ?? size : size
            },
        ],
        isVertical: [(_, p) => [p.placement], (placement) => ['left', 'right'].includes(placement)],
        isStart: [(_, p) => [p.placement], (placement) => ['left', 'top'].includes(placement)],
    }),
    listeners(({ cache, props, actions, values }) => ({
        beginResize: ({ startXOrY }) => {
            if (!props.containerRef.current) {
                return
            }

            let isDoubleClick = cache.firstClickTimestamp && Date.now() - cache.firstClickTimestamp < 500
            cache.firstClickTimestamp = Date.now()

            const originContainerBounds = props.containerRef.current.getBoundingClientRect()
            const originContainerBoundsSize = values.isVertical
                ? originContainerBounds.width
                : originContainerBounds.height

            let isClosed = props.closeThreshold ? originContainerBoundsSize < props.closeThreshold : false

            removeAllListeners(cache)
            cache.originXOrY = startXOrY

            const calculateEvent = (e: MouseEvent): ResizerEvent => {
                // desired width is based on the change relative to the original bounds
                // The resizer could be on the left or the right, so we need to account for this
                const eventSize = values.isVertical ? e.pageX : e.pageY
                const difference = eventSize - cache.originXOrY
                const desiredSize = values.isStart
                    ? originContainerBoundsSize - difference
                    : originContainerBoundsSize + difference

                return { desiredSize }
            }

            cache.onMouseMove = (e: MouseEvent): void => {
                const event = calculateEvent(e)
                actions.setResizingSize(event.desiredSize)
                isDoubleClick = false

                const newIsClosed = props.closeThreshold ? event.desiredSize < props.closeThreshold : false

                if (newIsClosed !== isClosed) {
                    props.onToggleClosed?.(newIsClosed)
                }

                isClosed = newIsClosed
            }
            cache.onMouseUp = (e: MouseEvent): void => {
                if (e.button === 0) {
                    const event = calculateEvent(e)

                    if (isDoubleClick) {
                        // Double click - reset to original width
                        actions.resetDesiredSize()
                        cache.firstClickTimestamp = null

                        props.onDoubleClick?.()
                    } else if (event.desiredSize !== values.size) {
                        if (!isClosed) {
                            // We only want to persist the value if it is open
                            actions.setDesiredSize(event.desiredSize)
                        }

                        posthog.capture('element resized', {
                            key: props.logicKey,
                            newWidth: event.desiredSize,
                            originalWidth: originContainerBounds.width,
                            isClosed,
                        })
                    }

                    actions.endResize()

                    removeAllListeners(cache)
                }
            }
            document.addEventListener('mousemove', cache.onMouseMove)
            document.addEventListener('mouseup', cache.onMouseUp)
        },

        endResize: () => {
            removeAllListeners(cache)
        },
    })),

    beforeUnmount(({ cache }) => {
        removeAllListeners(cache)
    }),
])
