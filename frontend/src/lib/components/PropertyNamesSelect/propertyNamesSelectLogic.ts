import { kea } from 'kea'

import { propertySelectLogicType } from './propertyNamesSelectLogicType'
export const propertySelectLogic = kea<propertySelectLogicType>({
    props: {
        propertySelectLogicKey: '' as string,

        properties: [] as string[],
        initialProperties: undefined as Set<string> | undefined,

        // eslint-disable-next-line @typescript-eslint/no-unused-vars, no-unused-vars
        onChange: undefined as ((_: string[]) => void) | undefined,
    },

    key: (props) => props.propertySelectLogicKey,

    actions: {
        setPopoverTriggerElement: (triggerElement: HTMLElement | null) => ({ triggerElement }),
        hidePopover: true,
        openPopover: true,
        togglePopover: true,

        setSelectedProperties: (newSelectedProperties: string[]) => ({
            newSelectedProperties: new Set(newSelectedProperties),
        }),

        toggleProperty: (property: string) => ({ property }),
        clearAll: true,
        selectAll: true,

        setQuery: (query: string) => ({ query }),
    },

    reducers: ({ props }) => ({
        isPopoverOpen: [
            false,
            {
                hidePopover: () => false,
                openPopover: () => true,
            },
        ],
        popoverTriggerElement: [
            null as HTMLElement | null,
            {
                setPopoverTriggerElement: (_, { triggerElement }) => triggerElement,
            },
        ],

        selectedProperties: [
            new Set(props.initialProperties || []),
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
            },
        ],

        query: [
            '' as string,
            {
                setQuery: (_, { query }) => query,
            },
        ],
    }),

    selectors: () => ({
        selectState: [
            (selectors) => [selectors.selectedProperties, selectors.properties],
            (selectedProperties, allProperties) =>
                selectedProperties.size === allProperties.length
                    ? 'all'
                    : selectedProperties.size === 0
                    ? 'none'
                    : 'some',
        ],

        isSelected: [
            (selectors) => [selectors.selectedProperties],
            (selectedProperties: Set<string>) => (propertyName: string) => selectedProperties.has(propertyName),
        ],

        properties: [() => [(_, props) => props.properties], (properties: string[]) => properties],

        filteredProperties: [
            (selectors) => [selectors.properties, selectors.query],
            (properties, query) =>
                query === ''
                    ? properties.map((property) => ({ name: property, highlightedNameParts: [property] }))
                    : properties
                          // First we split on query term, case insensitive, and globally,
                          // not just the first
                          // NOTE: it's important to use a capture group here, otherwise
                          // the query string match will not be included as a part. See
                          // https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/split#splitting_with_a_regexp_to_include_parts_of_the_separator_in_the_result
                          // for details
                          .map((property) => ({
                              name: property,
                              highlightedNameParts: property.split(new RegExp(`(${query})`, 'gi')),
                          }))
                          // Then filter where we have a match
                          .filter((property) => property.highlightedNameParts.length > 1),
        ],
    }),

    events: ({ cache, values, actions }) => ({
        afterMount: () => {
            cache.checkIfClickedOutside = (event: MouseEvent): void => {
                if (
                    values.isPopoverOpen &&
                    values.popoverTriggerElement &&
                    event.target instanceof Node &&
                    !values.popoverTriggerElement.contains(event.target)
                ) {
                    actions.hidePopover()
                }
            }
            document.addEventListener('mousedown', cache.checkIfClickedOutside)
        },
        beforeUnmount: () => {
            document.removeEventListener('mousedown', cache.checkIfClickedOutside)
        },
    }),

    listeners: ({ props, values, actions }) => ({
        togglePopover: () => {
            if (values.isPopoverOpen) {
                actions.hidePopover()
            } else {
                actions.openPopover()
            }
        },
        hidePopover: () => {
            // When the popover is hidden, we want to notify onChange with the
            // current selected properties
            if (props.onChange) {
                props.onChange(Array.from(values.selectedProperties))
            }
        },
        selectAll: () => {
            actions.setSelectedProperties(values.properties)
        },
    }),
})
