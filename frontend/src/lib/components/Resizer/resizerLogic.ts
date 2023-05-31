import { actions, kea, listeners, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import type { resizerLogicType } from './resizerLogicType'

export type ResizerLogicProps = {
    onResize: (event: { originX: number; desiredX: number; finished: boolean }) => void
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
    listeners(({ cache }) => ({
        beginResize: ({ startX }) => {
            cache.originX = startX
        },
    })),
    subscriptions(({ cache, actions, props }) => ({
        isResizeInProgress: (isResizeInProgress) => {
            if (isResizeInProgress) {
                cache.onMouseMove = (e: MouseEvent): void => {
                    props.onResize({ originX: cache.originX, desiredX: e.pageX, finished: false })
                }
                cache.onMouseUp = (e: MouseEvent): void => {
                    if (e.button === 0) {
                        actions.endResize()
                        props.onResize({ originX: cache.originX, desiredX: e.pageX, finished: true })
                    }
                }
                document.addEventListener('mousemove', cache.onMouseMove)
                document.addEventListener('mouseup', cache.onMouseUp)
                return () => {}
            } else {
                document.removeEventListener('mousemove', cache.onMouseMove)
                document.removeEventListener('mouseup', cache.onMouseUp)
            }
        },
    })),
])
