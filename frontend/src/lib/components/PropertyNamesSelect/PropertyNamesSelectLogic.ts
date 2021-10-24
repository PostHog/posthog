import { kea } from 'kea'

import { propertySelectLogicType } from './PropertyNamesSelectLogicType'

export const propertySelectLogic = kea<propertySelectLogicType>({
    props: {
        selectionKey: '' as string,
        onHide: () => {},
    },

    key: (props) => props.selectionKey,

    actions: {
        setTriggerElement: (triggerElement: HTMLElement | null) => ({ triggerElement }),
        hide: true,
        open: true,
        toggle: true,
    },

    reducers: {
        isOpen: [
            false,
            {
                hide: () => false,
                open: () => true,
                toggle: (isOpen) => !isOpen,
            },
        ],
        triggerElement: [
            null as HTMLElement | null,
            {
                setTriggerElement: (_, { triggerElement }) => triggerElement,
            },
        ],
    },

    events: ({ cache, values, actions }) => ({
        afterMount: () => {
            cache.checkIfClickedOutside = (event: MouseEvent): void => {
                if (
                    values.isOpen &&
                    values.triggerElement &&
                    event.target instanceof Node &&
                    !values.triggerElement.contains(event.target)
                ) {
                    actions.hide()
                }
            }
            document.addEventListener('mousedown', cache.checkIfClickedOutside)
        },
        beforeUnmount: () => {
            document.removeEventListener('mousedown', cache.checkIfClickedOutside)
        },
    }),

    listeners: ({ props: { onHide } }) => ({
        hide: () => {
            if (onHide) {
                onHide()
            }
        },
    }),
})
