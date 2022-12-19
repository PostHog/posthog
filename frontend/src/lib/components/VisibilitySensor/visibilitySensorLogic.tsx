import { kea } from 'kea'

import type { visibilitySensorLogicType } from './visibilitySensorLogicType'
export const visibilitySensorLogic = kea<visibilitySensorLogicType>({
    path: (key) => ['lib', 'components', 'VisibilitySensor', 'visibilitySensorLogic', key],
    props: {} as {
        id: string
        offset?: number
    },

    key: (props) => props.id || 'undefined',

    actions: () => ({
        setVisible: (visible: boolean) => ({ visible }),
        scrolling: (element: HTMLElement) => ({ element }),
    }),

    reducers: () => ({
        visible: [
            false,
            {
                setVisible: (_, { visible }) => visible,
            },
        ],
    }),

    windowValues: {
        innerHeight: (window) => window.innerHeight,
    },

    listeners: ({ actions, values }) => ({
        scrolling: async ({ element }, breakpoint) => {
            await breakpoint(500)

            if (values.checkIsVisible(element) && !values.visible) {
                actions.setVisible(true)
            } else if (!values.checkIsVisible(element) && values.visible) {
                actions.setVisible(false)
            }
        },
    }),

    selectors: () => ({
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
    }),
})
