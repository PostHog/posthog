import { actions, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { resizerLogicType } from './resizerLogicType'
import posthog from 'posthog-js'

export type ResizerEvent = {
    originX: number
    desiredX: number
    finished: boolean
    originWidth: number
    desiredWidth: number
}

export type ResizerLogicProps = {
    /** Specifying a persistence key, will store the desired resize values in localstorage */
    persistentKey?: string
    /** Where the resizer is placed - the width increases as the mouse moves {placement}   */
    placement: 'left' | 'right'
    containerRef: React.RefObject<HTMLDivElement>
    onResize?: (event: ResizerEvent) => void
    /** At what width, should this rather be considered a "close" event */
    closeThreshold?: number
    /** Fired when the "closeThreshold" is crossed */
    onToggleClosed?: (closed: boolean) => void
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
    key((props) => props.persistentKey ?? 'temporary'),
    path((key) => ['components', 'resizer', 'resizerLogic', key]),
    actions({
        beginResize: (startX: number) => ({ startX }),
        endResize: true,
        setResizingWidth: (width: number | null) => ({ width }),
        setDesiredWidth: (width: number | null) => ({ width }),
        resetDesiredWidth: true,
    }),
    reducers({
        isResizeInProgress: [
            false,
            {
                beginResize: () => true,
                endResize: () => false,
            },
        ],
        width: [
            null as number | null,
            { persist: true },
            {
                setDesiredWidth: (_, { width }) => width,
                resetDesiredWidth: () => null,
            },
        ],
        resizingWidth: [
            null as number | null,
            {
                setResizingWidth: (_, { width }) => width,
                beginResize: () => null,
                endResize: () => null,
            },
        ],
    }),
    selectors({
        desiredWidth: [
            (s) => [s.width, s.resizingWidth, s.isResizeInProgress],
            (width, resizingWidth, isResizeInProgress) => {
                return isResizeInProgress ? resizingWidth ?? width : width
            },
        ],
    }),
    listeners(({ cache, props, actions, values }) => ({
        beginResize: ({ startX }) => {
            if (!props.containerRef.current) {
                return
            }

            const isDoubleClick = cache.firstClickTimestamp && Date.now() - cache.firstClickTimestamp < 200
            cache.firstClickTimestamp = Date.now()

            const originContainerBounds = props.containerRef.current.getBoundingClientRect()

            let isClosed = props.closeThreshold ? originContainerBounds.width < props.closeThreshold : false

            removeAllListeners(cache)
            cache.originX = startX

            const calculateEvent = (e: MouseEvent, finished: boolean): ResizerEvent => {
                // desired width is based on the change relative to the original bounds
                // The resizer could be on the left or the right, so we need to account for this

                const desiredWidth =
                    props.placement === 'left'
                        ? originContainerBounds.width - (e.pageX - cache.originX)
                        : originContainerBounds.width + (e.pageX - cache.originX)

                return {
                    originX: cache.originX,
                    desiredX: e.pageX,
                    originWidth: originContainerBounds.width,
                    desiredWidth,
                    finished,
                }
            }

            cache.onMouseMove = (e: MouseEvent): void => {
                const event = calculateEvent(e, false)
                props.onResize?.(event)
                actions.setResizingWidth(event.desiredWidth)

                const newIsClosed = props.closeThreshold ? event.desiredWidth < props.closeThreshold : false

                if (newIsClosed !== isClosed) {
                    props.onToggleClosed?.(newIsClosed)
                }

                isClosed = newIsClosed
            }
            cache.onMouseUp = (e: MouseEvent): void => {
                if (e.button === 0) {
                    const event = calculateEvent(e, false)

                    if (event.desiredWidth !== values.width) {
                        if (!isClosed) {
                            // We only want to persist the value if it is open
                            actions.setDesiredWidth(event.desiredWidth)
                        }

                        props.onResize?.(event)

                        posthog.capture('element resized', {
                            key: props.persistentKey,
                            newWidth: event.desiredWidth,
                            originalWidth: originContainerBounds.width,
                            isClosed,
                        })
                    } else if (isDoubleClick) {
                        // Double click - reset to original width
                        actions.resetDesiredWidth()
                        cache.firstClickTimestamp = null
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
