import React from 'react'
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
        setElementRef: (elementRef: React.MutableRefObject<HTMLDivElement | null>) => ({ elementRef }),
        scrolling: true,
    }),

    reducers: () => ({
        visible: [
            false,
            {
                setVisible: (_, { visible }) => visible,
            },
        ],

        elementRef: [
            null as React.MutableRefObject<HTMLDivElement | null> | null,
            {
                setElementRef: (_, { elementRef }) => elementRef,
            },
        ],
    }),

    windowValues: {
        innerHeight: (window) => window.innerHeight,
    },

    listeners: ({ actions, values, props }) => ({
        scrolling: async (_, breakpoint) => {
            await breakpoint(200)

            const windowHeight = values.innerHeight
            const element = values.elementRef.current

            if (!element) {actions.setVisible(false)}

            const top = element.getBoundingClientRect().top
            if (top + props.offset >= 0 && top + props.offset <= windowHeight) {
                console.log('visible!')
                actions.setVisible(true)
            } else {
                console.log('Not visible!')
                actions.setVisible(false)
            }
        },
    }),

    // selectors: () => ({
    //     checkIsVisible: [
    //         (selectors) => [selectors.innerHeight, selectors.elementRef, (_, props) => props.offset],
    //         (windowHeight, elementRef, offset) => {
    //             if (!elementRef.current) return false
    //             const { top } = elementRef.current.getBoundingClientRect()
    //             return top + offset >= 0 && top + offset <= windowHeight
    //         },
    //     ],
    // }),

    events: ({ actions }) => ({
        afterMount: () => {
            document.addEventListener('scroll', actions.scrolling)
        },
        beforeUnmount: () => {
            document.removeEventListener('scroll', actions.scrolling)
        },
    }),
})
