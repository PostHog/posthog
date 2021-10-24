import CaretDownFilled from '@ant-design/icons/lib/icons/CaretDownFilled'
import SearchOutlined from '@ant-design/icons/lib/icons/SearchOutlined'
import WarningFilled from '@ant-design/icons/lib/icons/WarningFilled'
import { Checkbox, Input } from 'antd'
import { kea, MakeLogicType, useActions, useValues } from 'kea'
import { usePersonProperties } from 'lib/api/person-properties'
import React from 'react'
import { PersonProperty } from '~/types'
import './styles.scss'

import { propertySelectLogicType } from './PropertyNamesSelectType'
export const PropertyNamesSelect = ({
    onChange,
}: {
    onChange?: (selectedProperties: string[]) => void
}): JSX.Element => {
    /*
        Provides a super simple multiselect box for selecting property names.
    */

    const { properties, error } = usePersonProperties()

    return error ? (
        <div className="property-names-select">
            <WarningFilled style={{ color: 'var(--warning)' }} /> Error loading properties!
        </div>
    ) : properties ? (
        <PropertyNamesSelectBox onChange={onChange} properties={properties} />
    ) : (
        <div className="property-names-select">Loading properties...</div>
    )
}

export const PropertyNamesSelectBox = ({
    properties,
    initialProperties,
    onChange,
}: {
    properties: PersonProperty[]
    initialProperties?: string[]
    onChange?: (selectedProperties: string[]) => void
}): JSX.Element => {
    const selectProps = useSelectedProperties({
        properties,
        initialProperties,
    })

    const { selectedProperties, selectAll, clearAll, selectState } = selectProps

    const {
        isOpen: isSearchOpen,
        popoverProps,
        triggerProps,
    } = usePopover({
        onHide: () => {
            if (onChange) {
                onChange(Array.from(selectedProperties))
            }
        },
    })

    return (
        <div className="property-names-select-container" {...triggerProps}>
            <div className="property-names-select" role="combobox">
                {properties ? (
                    <>
                        {selectState === 'all' ? (
                            <Checkbox
                                checked={true}
                                aria-label="Select all"
                                onClick={(evt) => {
                                    clearAll()

                                    if (onChange) {
                                        onChange([])
                                    }
                                    evt.stopPropagation()
                                }}
                            />
                        ) : selectState === 'none' ? (
                            <Checkbox
                                checked={false}
                                aria-label="Select all"
                                onClick={(evt) => {
                                    selectAll()

                                    if (onChange) {
                                        onChange(properties.map((property) => property.name))
                                    }
                                    evt.stopPropagation()
                                }}
                            />
                        ) : (
                            <Checkbox
                                aria-label="Select all"
                                indeterminate={true}
                                onClick={(evt) => {
                                    selectAll()

                                    if (onChange) {
                                        onChange(properties.map((property) => property.name))
                                    }
                                    evt.stopPropagation()
                                }}
                            />
                        )}

                        <div className="selection-status-text">
                            {selectedProperties.size} of {properties.length} selected
                        </div>

                        <CaretDownFilled />
                    </>
                ) : (
                    'Loading properties'
                )}
            </div>
            {isSearchOpen ? (
                <div className="popover" {...popoverProps}>
                    <SelectPropertiesProvider {...selectProps}>
                        <PropertyNamesSearch />
                    </SelectPropertiesProvider>
                </div>
            ) : null}
        </div>
    )
}

const PropertyNamesSearch = (): JSX.Element => {
    const { properties, toggleProperty, isSelected } = useSelectedPropertiesContext()
    const { filteredProperties, query, setQuery } = usePropertySearch(properties)

    return (
        <>
            <Input
                onChange={({ target: { value } }) => setQuery(value)}
                allowClear
                className="search-box"
                placeholder="Search for properties"
                prefix={<SearchOutlined />}
            />
            <div className="search-results">
                {filteredProperties.length ? (
                    filteredProperties.map((property) => (
                        <Checkbox
                            key={property.name}
                            className={'checkbox' + (isSelected(property.name) ? ' checked' : '')}
                            checked={isSelected(property.name)}
                            onChange={() => toggleProperty(property.name)}
                        >
                            {property.highlightedName}
                        </Checkbox>
                    ))
                ) : (
                    <p className="no-results-message">
                        No properties match <b>“{query}”</b>. Refine your search to try again.
                    </p>
                )}
            </div>
        </>
    )
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type, @typescript-eslint/explicit-module-boundary-types
const usePopover = ({ onHide }: { onHide: () => void }) => {
    // Provides logic for opening and closing the popover. Note that we wrap the
    // logic such that we can generate a unique key and ensure for each
    // invocation

    // Make sure to create a new state for each component
    const propertySelectLogicKey = React.useMemo(() => Math.random().toString(), [])

    const logic = propertySelectLogic({ selectionKey: propertySelectLogicKey, onHide })
    const { toggle, setTriggerElement, ...actions } = useActions(logic)

    return {
        toggle,
        setTriggerElement,
        ...actions,
        ...useValues(logic),
        popoverProps: {
            onClick(event: React.MouseEvent): void {
                // Avoid the click propogating to the trigger element. We need
                // to do this in order to prevent popover clicks also triggering
                // anything on containing elements
                event.stopPropagation()
            },
        },
        triggerProps: {
            onClick: toggle,
            ref: setTriggerElement,
        },
    }
}

const propertySelectLogic = kea<propertySelectLogicType>({
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
                // eslint-disable-next-line no-unused-vars, @typescript-eslint/no-unused-vars
                hide: (_, {}) => false,
                // eslint-disable-next-line no-unused-vars, @typescript-eslint/no-unused-vars
                open: (_, {}) => true,
                toggle: (isOpen, {}) => !isOpen,
            },
        ],
        triggerElement: [
            null,
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

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
const usePropertySearch = (properties: PersonProperty[]) => {
    /*
        Basic case insensitive substring search functionality for person property
        selection. It's pretty much this stackoverflow answer:
        https://stackoverflow.com/a/43235785
    */
    const [query, setQuery] = React.useState<string>('')
    const filteredProperties = React.useMemo(() => {
        return query === ''
            ? properties.map((property) => ({ ...property, highlightedName: property.name }))
            : properties
                  // First we split on query term, case insensitive, and globally,
                  // not just the first
                  // NOTE: it's important to use a capture group here, otherwise
                  // the query string match will not be included as a part. See
                  // https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/split#splitting_with_a_regexp_to_include_parts_of_the_separator_in_the_result
                  // for details
                  .map((property) => ({
                      ...property,
                      nameParts: property.name.split(new RegExp(`(${query})`, 'gi')),
                  }))
                  // Then filter where we have a match
                  .filter((property) => property.nameParts.length > 1)
                  // Then create a JSX.Element that can be rendered
                  .map((property) => ({
                      ...property,
                      highlightedName: (
                          <span>
                              {property.nameParts.map((part, index) =>
                                  part.toLowerCase() === query.toLowerCase() ? (
                                      <b key={index}>{part}</b>
                                  ) : (
                                      <React.Fragment key={index}>{part}</React.Fragment>
                                  )
                              )}
                          </span>
                      ),
                  }))
    }, [query, properties])

    return { filteredProperties, setQuery, query }
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type, @typescript-eslint/explicit-module-boundary-types
export const useSelectedProperties = ({
    properties,
    initialProperties,
    onChange,
}: {
    properties: PersonProperty[]
    initialProperties?: string[]
    onChange?: (selectedProperties: string[]) => void
}) => {
    const [selectedProperties, setSelectedPropertiesSet] = React.useState<Set<string>>(
        new Set(initialProperties || properties.map((property) => property.name))
    )

    const setSelectedProperties = (newSelectedProperties: string[]): void => {
        setAndNotify(new Set(newSelectedProperties))
    }

    const setAndNotify = (newSelectedProperties: Set<string>): void => {
        setSelectedPropertiesSet(newSelectedProperties)

        if (onChange) {
            onChange(Array.from(newSelectedProperties))
        }
    }

    const toggleProperty = (property: string): void => {
        setAndNotify(
            selectedProperties.has(property)
                ? new Set(Array.from(selectedProperties).filter((p) => p !== property))
                : new Set([...Array.from(selectedProperties), property])
        )
    }

    const clearAll = (): void => {
        setAndNotify(new Set())
    }

    const selectAll = (): void => {
        setAndNotify(new Set(properties.map((property) => property.name)))
    }

    const isSelected = (property: string): boolean => selectedProperties.has(property)

    const selectState: 'all' | 'none' | 'some' =
        selectedProperties.size === properties.length ? 'all' : selectedProperties.size === 0 ? 'none' : 'some'

    return {
        properties,
        selectedProperties,
        setSelectedProperties,
        toggleProperty,
        clearAll,
        selectAll,
        selectState,
        isSelected,
    }
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type, @typescript-eslint/explicit-module-boundary-types
export const useSelectedPropertiesContext = () => {
    /* Provides functions for handling selected properties state */
    const context = React.useContext(propertiesSelectionContext)

    // make typing happy, i.e. rule out the undefined case so we don't have to
    // check this everywhere
    if (context === undefined) {
        throw Error('No select React.Context found')
    }

    return context
}

/*
A propertiesSelectionContext provides:

    - selectedProperties: a set of selected property names
    - state manipulation functions for modifying the set of selected properties
*/
type PropertiesSelectionContextType = {
    properties: PersonProperty[]
    selectState: 'all' | 'none' | 'some'
    selectedProperties: Set<string>
    toggleProperty: (propertyName: string) => void
    clearAll: () => void
    selectAll: () => void
    isSelected: (propertyName: string) => boolean
}

const propertiesSelectionContext = React.createContext<PropertiesSelectionContextType | undefined>(undefined)

export const SelectPropertiesProvider = ({
    children,
    ...methods
}: PropertiesSelectionContextType & {
    children: JSX.Element[] | JSX.Element
}): JSX.Element => {
    return <propertiesSelectionContext.Provider value={methods}>{children}</propertiesSelectionContext.Provider>
}
