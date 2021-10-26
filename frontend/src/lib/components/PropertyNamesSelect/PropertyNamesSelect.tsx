import CaretDownFilled from '@ant-design/icons/lib/icons/CaretDownFilled'
import SearchOutlined from '@ant-design/icons/lib/icons/SearchOutlined'
import { Checkbox, Input } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import React from 'react'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { PersonProperty } from '~/types'
import { propertySelectLogic } from './PropertyNamesSelectLogic'
import './styles.scss'

// Incrementing counter to ensure uniqueness of logic for each component
let propertyNameSelectCounter = 0

export const PropertyNamesSelect = ({
    onChange,
    initialProperties = new Set(),
}: {
    onChange?: (selectedProperties: string[]) => void
    initialProperties?: Set<string>
}): JSX.Element => {
    /*
        Provides a super simple multiselect box for selecting property names.
    */
    const { personProperties: properties } = useValues(personPropertiesModel)

    // Make a key that identifies the logic for this specific component instance
    const propertySelectLogicKey = React.useMemo(() => propertyNameSelectCounter++, [])

    // NOTE: I'm checking that length > 0 here, although this seems a little
    // hacky. I'm doing this so when we instantiate the propertySelectLogic with
    // props, we have the props to hand as they will not update on rerender
    return properties?.length ? (
        <BindLogic
            logic={propertySelectLogic}
            props={{ properties, propertySelectLogicKey, initialProperties, onChange }}
        >
            <PropertyNamesSelectBox onChange={onChange} properties={properties} />
        </BindLogic>
    ) : (
        <div className="property-names-select">Loading properties...</div>
    )
}

export const PropertyNamesSelectBox = ({
    properties,
    onChange,
}: {
    properties: PersonProperty[]
    onChange?: (selectedProperties: string[]) => void
}): JSX.Element => {
    const {
        // popover actions/values
        isOpen: isSearchOpen,

        // selection actions/values
        selectedProperties,
        selectState,
    } = useValues(propertySelectLogic)

    const {
        // popover actions/values
        toggle,
        setTriggerElement,

        // selection actions/values
        selectAll,
        clearAll,
    } = useActions(propertySelectLogic)

    return (
        <div className="property-names-select-container" onClick={toggle} ref={setTriggerElement}>
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
