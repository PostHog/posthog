import CaretDownFilled from '@ant-design/icons/lib/icons/CaretDownFilled'
import SearchOutlined from '@ant-design/icons/lib/icons/SearchOutlined'
import WarningFilled from '@ant-design/icons/lib/icons/WarningFilled'
import { Checkbox, Input } from 'antd'
import { usePersonProperies } from 'lib/api/person-properties'
import React from 'react'
import { PersonProperty } from '~/types'
import './styles.scss'

export const PropertyNamesSelect = ({
    onChange,
}: {
    onChange?: (selectedProperties: string[]) => void
}): JSX.Element => {
    /*
        Provides a super simple multiselect box for selecting property names.
    */

    const { properties, error } = usePersonProperies()

    return error ? (
        <div className="property-names-select">
            <WarningFilled style={{ color: 'var(--warning)' }} /> Error loading properties!
        </div>
    ) : properties ? (
        <SelectPropertiesProvider properties={properties}>
            <PropertyNamesSelectBox onBlur={onChange} />
        </SelectPropertiesProvider>
    ) : (
        <div className="property-names-select">Loading properties...</div>
    )
}

const PropertyNamesSelectBox = ({ onBlur }: { onBlur?: (selectedProperties: string[]) => void }): JSX.Element => {
    const { properties, selectedProperties, selectAll, clearAll, selectState } = useSelectedProperties()
    const {
        isOpen: isSearchOpen,
        popoverProps,
        triggerProps,
    } = usePopover({
        onHide: () => {
            if (onBlur) {
                onBlur(Array.from(selectedProperties))
            }
        },
    })

    return (
        <div className="property-names-select-container" {...triggerProps}>
            <div className="property-names-select">
                {properties ? (
                    <>
                        {selectState === 'all' ? (
                            <Checkbox
                                checked={true}
                                onClick={(evt) => {
                                    clearAll()
                                    evt.stopPropagation()
                                }}
                            />
                        ) : selectState === 'none' ? (
                            <Checkbox
                                checked={false}
                                onClick={(evt) => {
                                    selectAll()
                                    evt.stopPropagation()
                                }}
                            />
                        ) : (
                            <Checkbox
                                indeterminate={true}
                                onClick={(evt) => {
                                    selectAll()
                                    evt.stopPropagation()
                                }}
                            />
                        )}

                        <div className="selection-status-text">
                            {selectedProperties.size} or {properties.length} selected
                        </div>

                        <CaretDownFilled />
                    </>
                ) : (
                    'Loading properties'
                )}
            </div>
            {isSearchOpen ? (
                <div className="popover" {...popoverProps}>
                    <PropertyNamesSearch />
                </div>
            ) : null}
        </div>
    )
}

const PropertyNamesSearch = (): JSX.Element => {
    const { properties, toggleProperty, isSelected } = useSelectedProperties()
    const { filteredProperties, query, setQuery } = usePropertySearch(properties)

    return (
        <>
            <Input
                onChange={({ target: { value } }) => setQuery(value)}
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
                            {property.name}
                        </Checkbox>
                    ))
                ) : (
                    <p className="no-results-message">
                        No properties match “{query}”. Refine your search to try again.
                    </p>
                )}
            </div>
        </>
    )
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
const usePopover = ({ onHide }: { onHide: () => void }) => {
    /* Logic for handling arbitrary popover state */
    const [isOpen, setIsOpen] = React.useState<boolean>(false)

    const hide = (): void => {
        setIsOpen(false)
        onHide()
    }

    const open = (): void => setIsOpen(true)

    const toggle = (): void => {
        if (isOpen) {
            hide()
        } else {
            open()
        }
    }

    // I use a ref to ensure we are able to close the popover when the user clicks outside of it.
    const triggerRef = React.useRef<HTMLDivElement>(null)

    React.useEffect(() => {
        const checkIfClickedOutside = (event: MouseEvent): void => {
            if (
                isOpen &&
                triggerRef.current &&
                event.target instanceof Node &&
                !triggerRef.current.contains(event.target)
            ) {
                hide()
            }
        }

        document.addEventListener('mousedown', checkIfClickedOutside)

        return () => {
            // Cleanup the event listener
            document.removeEventListener('mousedown', checkIfClickedOutside)
        }
    }, [isOpen])

    return {
        isOpen,
        open,
        hide,
        toggle,
        // Return props that should be on the actual popover. This is so we can
        // position things correctly
        popoverProps: {
            onClick(event: React.MouseEvent): void {
                // Avoid the click propogating to the trigger element. We need
                // to do this in order to prevent popover clicks also triggering
                // anything on containing elements
                event.stopPropagation()
            },
        },
        // Return propse that should be on the trigger. This is so we can attach
        // any show, hide handlers etc.
        triggerProps: { ref: triggerRef, onClick: toggle },
    }
}

const usePropertySearch = (
    properties: PersonProperty[]
): { filteredProperties: PersonProperty[]; setQuery: (query: string) => void; query: string } => {
    /* Basic case insensitive substring search functionality for person property selection */
    const [query, setQuery] = React.useState<string>('')
    const filteredProperties = React.useMemo(() => {
        return properties.filter((property) => property.name.toLowerCase().includes(query.toLowerCase()))
    }, [query, properties])

    return { filteredProperties, setQuery, query }
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
const useSelectedProperties = () => {
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
const propertiesSelectionContext = React.createContext<
    | {
          properties: PersonProperty[]
          selectState: 'all' | 'none' | 'some'
          selectedProperties: Set<string>
          toggleProperty: (propertyName: string) => void
          clearAll: () => void
          selectAll: () => void
          isSelected: (propertyName: string) => boolean
      }
    | undefined
>(undefined)

const SelectPropertiesProvider = ({
    properties,
    onChange,
    children,
}: {
    properties: PersonProperty[]
    children: React.ReactNode
    onChange?: (selectedProperties: string[]) => void
}): JSX.Element => {
    const [selectedProperties, setSelectedProperties] = React.useState<Set<string>>(
        new Set(properties.map((property) => property.name))
    )

    const setAndNotify = (newSelectedProperties: Set<string>): void => {
        setSelectedProperties(newSelectedProperties)

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

    return (
        <propertiesSelectionContext.Provider
            value={{ properties, selectedProperties, toggleProperty, clearAll, selectAll, selectState, isSelected }}
        >
            {children}
        </propertiesSelectionContext.Provider>
    )
}
