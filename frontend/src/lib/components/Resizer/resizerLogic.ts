import { actions, beforeUnmount, kea, listeners, path, props, reducers } from 'kea'

import type { resizerLogicType } from './resizerLogicType'

export type ResizerLogicProps = {
    onResize: (event: { originX: number; desiredX: number; finished: boolean }) => void
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
    path(['components', 'resizer', 'resizerLogic']),
    props({} as ResizerLogicProps),
    actions({
        beginResize: (startX: number) => ({ startX }),
        endResize: true,
    }),
    reducers({
        isResizeInProgress: [
            false,
            {
                beginResize: () => true,
                endResize: () => false,
            },
        ],
    }),
    listeners(({ cache, props, actions }) => ({
        beginResize: ({ startX }) => {
            removeAllListeners(cache)
            cache.originX = startX

            cache.onMouseMove = (e: MouseEvent): void => {
                props.onResize({ originX: cache.originX, desiredX: e.pageX, finished: false })
            }
            cache.onMouseUp = (e: MouseEvent): void => {
                if (e.button === 0) {
                    actions.endResize()
                    props.onResize({ originX: cache.originX, desiredX: e.pageX, finished: true })
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
