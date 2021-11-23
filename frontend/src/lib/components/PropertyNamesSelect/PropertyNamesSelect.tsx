import { SearchOutlined } from '@ant-design/icons'
import { Checkbox, Input } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import React from 'react'
import { propertySelectLogic } from './propertyNamesSelectLogic'
import './PropertyNamesSelect.scss'
import { IconArrowDropDown } from '../icons'

// Incrementing counter to ensure uniqueness of logic for each component
let propertyNameSelectCounter = 0

export const PropertyNamesSelect = ({
    onChange,
    value = new Set(),
    allProperties,
}: {
    onChange?: (selectedProperties: string[]) => void
    value?: Set<string>
    allProperties?: string[]
}): JSX.Element => {
    /*
        Provides a super simple multiselect box for selecting property names.
    */

    // Make a key that identifies the logic for this specific component instance
    const propertySelectLogicKey = React.useMemo(() => propertyNameSelectCounter++, [])

    return allProperties?.length ? (
        <BindLogic
            logic={propertySelectLogic}
            props={{ properties: allProperties, propertySelectLogicKey, value, onChange }}
        >
            <PropertyNamesSelectBox onChange={onChange} value={value} />
        </BindLogic>
    ) : (
        <div className="property-names-select">No properties available</div>
    )
}

export const PropertyNamesSelectBox = ({
    onChange,
    value,
}: {
    value: Set<string>
    onChange?: (selectedProperties: string[]) => void
}): JSX.Element => {
    const {
        // popover actions/values
        isPopoverOpen: isSearchOpen,

        // selection actions/values
        selectedProperties,
        properties,
        selectState,
    } = useValues(propertySelectLogic)

    const {
        // popover actions/values
        togglePopover,
        setPopoverTriggerElement,

        // selection actions/values
        selectAll,
        clearAll,
        setSelectedProperties,
    } = useActions(propertySelectLogic)

    // Explicitly set the selectedProperties on value change
    React.useEffect(() => {
        setSelectedProperties(Array.from(value))
    }, [value, setSelectedProperties])

    return (
        <div className="property-names-select-container" onClick={togglePopover} ref={setPopoverTriggerElement}>
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
                                        onChange(properties)
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
                                        onChange(properties)
                                    }
                                    evt.stopPropagation()
                                }}
                            />
                        )}

                        <div className="selection-status-text">
                            {selectedProperties.size} of {properties.length}
                        </div>
                        <span className="dropdown-icon">
                            <IconArrowDropDown />
                        </span>
                    </>
                ) : (
                    'Loading properties'
                )}
            </div>
            {isSearchOpen ? (
                <div
                    className="popover"
                    onClick={(event: React.MouseEvent) => {
                        // Avoid the click propogating to the trigger element. We need
                        // to do this in order to prevent popover clicks also triggering
                        // anything on containing elements
                        event.stopPropagation()
                    }}
                >
                    <PropertyNamesSearch />
                </div>
            ) : null}
        </div>
    )
}

const PropertyNamesSearch = (): JSX.Element => {
    const { query, filteredProperties, isSelected } = useValues(propertySelectLogic)
    const { setQuery, toggleProperty } = useActions(propertySelectLogic)

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
                            {property.highlightedNameParts.map((part, index) =>
                                part.toLowerCase() === query.toLowerCase() ? (
                                    <b key={index}>{part}</b>
                                ) : (
                                    <React.Fragment key={index}>{part}</React.Fragment>
                                )
                            )}
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
