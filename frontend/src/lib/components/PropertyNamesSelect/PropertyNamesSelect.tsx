import CaretDownFilled from '@ant-design/icons/lib/icons/CaretDownFilled'
import SearchOutlined from '@ant-design/icons/lib/icons/SearchOutlined'
import WarningFilled from '@ant-design/icons/lib/icons/WarningFilled'
import { Checkbox, Input } from 'antd'
import { useActions, useValues } from 'kea'
import { usePersonProperties } from 'lib/api/person-properties'
import React from 'react'
import { PersonProperty } from '~/types'
import { propertySelectLogic } from './PropertyNamesSelectLogic'
import './styles.scss'

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
    const selectProps = usePropertyNamesSelectLogic({
        properties,
        initialProperties,
    })

    const {
        // popover actions/values
        isOpen: isSearchOpen,
        popoverProps,
        triggerProps,

        // selection actions/values
        selectedProperties,
        selectAll,
        clearAll,
        selectState,
    } = selectProps

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
                    <PropertyNamesSearch />
                </div>
            ) : null}
        </div>
    )
}

const PropertyNamesSearch = (): JSX.Element => {
    const { properties, toggleProperty, isSelected } = usePropertyNamesSelectLogicContext()
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
const usePropertyNamesSelectLogic = ({
    onHide,
    properties,
    initialProperties,
    onChange,
}: {
    onHide: () => void
    properties: PersonProperty[]
    initialProperties: string[]
    onChange: (_: string[]) => void
}) => {
    // Provides logic for opening and closing the popover. Note that we wrap the
    // logic such that we can generate a unique key and ensure for each
    // invocation. We also make the logic independent of React specifics

    // Make sure to create a new state for each component.

    const propertySelectLogicKey = React.useMemo(() => Math.random().toString(), [])

    const logic = propertySelectLogic({
        selectionKey: propertySelectLogicKey,
        onHide,
        properties,
        initialProperties,
        onChange,
    })

    // popover actions/values
    const { toggle, setTriggerElement, hide, open } = useActions(logic)
    const { isOpen } = useValues(logic)

    // selection actions/values
    const { selectAll, clearAll, selectState } = useActions(logic)
    const { selectedProperties } = useValues(logic)

    return {
        // popover actions/values
        toggle,
        setTriggerElement,
        hide,
        open,
        isOpen,

        // React prop specifics
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

        // selection actions/values
        properties,
        selectedProperties,
        selectAll,
        clearAll,
        selectState,
    }
}

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
export const usePropertyNamesSelectLogicContext = () => {
    /* Provides functions for handling selected properties state */
    const logic = React.useContext(propertyNamesSelectLogicContext)

    // make typing happy, i.e. rule out the undefined case so we don't have to
    // check this everywhere
    if (logic === undefined) {
        throw Error('No select logic React.Context found')
    }

    return logic
}

/*
    A propertyNamesSelectLogicContext provides a way to share logic with child
    components
*/

const propertyNamesSelectLogicContext = React.createContext<typeof propertySelectLogic | undefined>(undefined)

export const SelectPropertiesProvider = ({
    children,
    logic,
}: { logic: typeof propertySelectLogic } & {
    children: JSX.Element[] | JSX.Element
}): JSX.Element => {
    return <propertyNamesSelectLogicContext.Provider value={logic}>{children}</propertyNamesSelectLogicContext.Provider>
}
