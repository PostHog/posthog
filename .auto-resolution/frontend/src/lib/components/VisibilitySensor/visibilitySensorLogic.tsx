import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { windowValues } from 'kea-window-values'

import type { visibilitySensorLogicType } from './visibilitySensorLogicType'

export const visibilitySensorLogic = kea<visibilitySensorLogicType>([
    props(
        {} as {
            id: string
            offset?: number
        }
    ),
    key((props) => props.id || 'undefined'),
    path((key) => ['lib', 'components', 'VisibilitySensor', 'visibilitySensorLogic', key]),
    actions(() => ({
        setVisible: (visible: boolean) => ({ visible }),
        scrolling: (element: HTMLElement) => ({ element }),
    })),
    windowValues({
        innerHeight: (window: Window) => window.innerHeight,
    }),
    reducers(() => ({
        visible: [
            false,
            {
                setVisible: (_, { visible }) => visible,
            },
        ],
    })),
    selectors(() => ({
        checkIsVisible: [
            (selectors) => [selectors.innerHeight, (_, props) => props.offset || 0],
            (windowHeight, offset) => (element: HTMLElement) => {
                if (!element) {
                    return false
                }
                const { top, bottom, left, right } = element.getBoundingClientRect()
                // happens when switching tabs, element is gone, but sensorLogic is still mounted
                if (top === 0 && bottom === 0 && left === 0 && right === 0) {
                    return false
                }
                return top + offset >= 0 && top + offset <= windowHeight
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        scrolling: async ({ element }, breakpoint) => {
            await breakpoint(500)

            if (values.checkIsVisible(element) && !values.visible) {
                actions.setVisible(true)
            } else if (!values.checkIsVisible(element) && values.visible) {
                actions.setVisible(false)
            }
        },
    })),
])
