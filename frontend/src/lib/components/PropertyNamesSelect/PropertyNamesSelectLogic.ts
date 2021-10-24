import { kea } from 'kea'
import { PersonProperty } from '~/types'

import { propertySelectLogicType } from './PropertyNamesSelectLogicType'

export const propertySelectLogic = kea<propertySelectLogicType>({
    props: {
        selectionKey: '' as string,
        onHide: () => {},

        properties: [] as PersonProperty[],
        initialProperties: [] as string[],

        // eslint-disable-next-line @typescript-eslint/no-unused-vars, no-unused-vars
        onChange: (_: string[]) => {},
    },

    key: (props) => props.selectionKey,

    actions: {
        setTriggerElement: (triggerElement: HTMLElement | null) => ({ triggerElement }),
        hide: true,
        open: true,
        toggle: true,

        setSelectedProperties: (newSelectedProperties: string[]) => ({
            newSelectedProperties: new Set(newSelectedProperties),
        }),

        toggleProperty: (property: string) => ({ property }),
        clearAll: true,
        selectAll: true,
    },

    reducers: ({ props }) => ({
        isOpen: [
            false,
            {
                hide: () => false,
                open: () => true,
            },
        ],
        triggerElement: [
            null as HTMLElement | null,
            {
                setTriggerElement: (_, { triggerElement }) => triggerElement,
            },
        ],

        selectedProperties: [
            new Set(),
            {
                setSelectedProperties: (_, { newSelectedProperties }) => new Set(newSelectedProperties),
                toggleProperty: (selectedProperties, { property }) => {
                    const newSelectedProperties = new Set(selectedProperties)
                    if (newSelectedProperties.has(property)) {
                        newSelectedProperties.delete(property)
                    } else {
                        newSelectedProperties.add(property)
                    }
                    return newSelectedProperties
                },
                clearAll: () => new Set([]),
                selectAll: () => new Set(props.properties.map((property) => property.name)),
            },
        ],
    }),

    selectors: {
        selectState: [
            [(selectors) => [selectors.selectedProperties, selectors.properties]],
            (selectedProperties, properties) =>
                selectedProperties.size === properties.length ? 'all' : selectedProperties.size === 0 ? 'none' : 'some',
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

    listeners: ({ props, values, actions }) => ({
        toggle: () => {
            if (values.isOpen) {
                actions.hide()
            } else {
                actions.open()
            }
        },
        hide: () => {
            // When the popover is hidden, we want to notify onChange with the
            // current selected properties
            props.onChange(Array.from(values.selectedProperties))
        },
    }),
})
