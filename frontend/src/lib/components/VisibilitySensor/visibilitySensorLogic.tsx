import { kea } from 'kea'

import { visibilitySensorLogicType } from './visibilitySensorLogicType'
export const visibilitySensorLogic = kea<visibilitySensorLogicType>({
    props: {} as {
        id: string
        offset: number
    },

    key: (props) => props.id || 'new',

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
            await breakpoint(200)

            if (values.checkIsVisible(element) && !values.visible) {
                console.log('now visible!')
                actions.setVisible(true)
            } else if (!values.checkIsVisible(element) && values.visible) {
                console.log('now Not visible!')
                actions.setVisible(false)
            }
            console.log('no op')
        },
    }),

    selectors: () => ({
        checkIsVisible: [
            (selectors) => [selectors.innerHeight, (_, props) => props.offset],
            (windowHeight, offset) => (element: HTMLElement) => {
                if (!element) {return false}
                const { top, bottom } = element.getBoundingClientRect()
                console.log(top, bottom, offset, windowHeight)
                return top + offset >= 0 && top + offset <= windowHeight
            },
        ],
    }),
})
