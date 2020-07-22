import React, { useRef, useState, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { EntityTypes } from '../trendsLogic'
import { CloseButton } from '~/lib/utils'
import { Dropdown } from '~/lib/components/Dropdown'
import { ActionFilterDropdown } from './ActionFilterDropdown'
import { Tooltip } from 'antd'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { userLogic } from 'scenes/userLogic'
import { DownOutlined, DragOutlined } from '@ant-design/icons'

const MATHS = {
    total: {
        name: 'Total volume',
        description: (
            <>
                Total event volume.
                <br />
                If a user performs an event 3 times on a given day, it counts as 3.
            </>
        ),
        onProperty: false,
    },
    dau: {
        name: 'DAU',
        description: (
            <>
                Daily active users.
                <br />
                If a user performs an event 3 times on a given day, it counts only as 1.
            </>
        ),
        onProperty: false,
    },
    sum: {
        name: 'Sum',
        description: (
            <>
                Event property sum.
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 42.
            </>
        ),
        onProperty: true,
    },
    avg: {
        name: 'Average',
        description: (
            <>
                Event property average.
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 14.
            </>
        ),
        onProperty: true,
    },
    min: {
        name: 'Minimum',
        description: (
            <>
                Event property minimum.
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 10.
            </>
        ),
        onProperty: true,
    },
    max: {
        name: 'Maximum',
        description: (
            <>
                Event property maximum.
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 20.
            </>
        ),
        onProperty: true,
    },
}

const determineFilterLabel = (visible, filter) => {
    if (visible) return 'Hide filters'
    if (filter.properties && Object.keys(filter.properties).length > 0) {
        return `${Object.keys(filter.properties).length} filter${
            Object.keys(filter.properties).length === 1 ? '' : 's'
        }`
    }
    return 'Add filters'
}

export function ActionFilterRow({ logic, filter, index, hideMathSelector, dragging }) {
    const node = useRef()
    const { selectedFilter, entities } = useValues(logic)
    const { selectFilter, updateFilterMath, removeLocalFilter, updateFilterProperty, setLayoutHeight } = useActions(
        logic
    )
    const { eventProperties } = useValues(userLogic)
    const [entityFilterVisible, setEntityFilterVisible] = useState(false)

    useEffect(() => {
        if (dragging) {
            setEntityFilterVisible(!dragging)
            setLayoutHeight(filter.id, !dragging, 0)
        }
    }, [dragging])

    let entity, name, value
    let math = filter.math
    let mathProperty = filter.math_property

    const onClose = () => {
        removeLocalFilter({ value: filter.id, type: filter.type, index })
    }
    const onMathSelect = (_, math) => {
        updateFilterMath({
            math,
            math_property: MATHS[math]?.onProperty ? mathProperty : undefined,
            onProperty: MATHS[math]?.onProperty,
            value: filter.id,
            type: filter.type,
            index: index,
        })
    }
    const onMathPropertySelect = (_, mathProperty) => {
        updateFilterMath({
            math: filter.math,
            math_property: mathProperty,
            value: filter.id,
            type: filter.type,
            index: index,
        })
    }

    const onPropertyChange = (properties, index) => {
        updateFilterProperty({ properties, index })
        setLayoutHeight(filter.id, entityFilterVisible, properties.length || 0)
    }

    const dropDownCondition = () =>
        selectedFilter && selectedFilter.type === filter.type && selectedFilter.index === index

    const onClick = () => {
        if (selectedFilter && selectedFilter.type === filter.type && selectedFilter.index === index) selectFilter(null)
        else selectFilter({ filter, type: filter.type, index })
    }

    const toggleEntityFilter = (entityFilterVisible) => {
        setEntityFilterVisible(!entityFilterVisible)
        const propertiesLength = (filter.properties && filter.properties.length) || 0
        setLayoutHeight(filter.id, !entityFilterVisible, propertiesLength)
    }

    if (filter.type === EntityTypes.NEW_ENTITY) {
        name = null
        value = null
    } else {
        entity = entities[filter.type].filter((action) => action.id === filter.id)[0] || {}
        name = entity.name || filter.name
        value = entity.id || filter.id
    }
    return (
        <div className="action-filter-row pb-1">
            <DragOutlined className="action-filter-row-handle mr-2 pt-2" />
            <button
                data-attr={'trend-element-subject-' + index}
                ref={node}
                className="filter-action btn btn-sm btn-light"
                type="button"
                onClick={onClick}
                style={{
                    fontWeight: 500,
                }}
            >
                {name || 'Select action'}
                <DownOutlined style={{ marginLeft: '3px', color: 'rgba(0, 0, 0, 0.25)' }} />
            </button>
            {!hideMathSelector && <MathSelector math={math} index={index} onMathSelect={onMathSelect} />}
            {!hideMathSelector && MATHS[math]?.onProperty && (
                <MathPropertySelector
                    name={name}
                    math={math}
                    mathProperty={mathProperty}
                    index={index}
                    onMathPropertySelect={onMathPropertySelect}
                    properties={eventProperties}
                />
            )}
            <div
                className="btn btn-sm btn-light ml-2"
                onClick={() => toggleEntityFilter(entityFilterVisible)}
                data-attr={'show-prop-filter-' + index}
            >
                {determineFilterLabel(entityFilterVisible, filter)}
            </div>
            <CloseButton
                className="ml-2"
                onClick={onClose}
                style={{
                    float: 'none',
                    position: 'absolute',
                    marginTop: 3,
                }}
            />
            {entityFilterVisible && (
                <div className="ml-3">
                    <PropertyFilters
                        pageKey={`${index}-${value}-filter`}
                        properties={eventProperties}
                        propertyFilters={filter.properties}
                        onChange={(properties) => onPropertyChange(properties, index)}
                        style={{ marginBottom: 0 }}
                    />
                </div>
            )}
            {dropDownCondition() && (
                <ActionFilterDropdown
                    logic={logic}
                    onClickOutside={(e) => {
                        if (node.current.contains(e.target)) {
                            return
                        }
                        selectFilter(null)
                    }}
                />
            )}
        </div>
    )
}

function MathSelector(props) {
    return (
        <Dropdown
            title={MATHS[props.math || 'total']?.name}
            buttonClassName="btn btn-sm btn-light ml-2"
            data-attr={`math-selector-${props.index}`}
        >
            {Object.entries(MATHS).map(([key, value]) => (
                <Tooltip placement="right" title={value.description} key={`math-${key}`}>
                    <a
                        href="#"
                        className="dropdown-item"
                        onClick={() => props.onMathSelect(props.index, key)}
                        data-attr={`math-${key}-${props.index}`}
                    >
                        {value.name}
                    </a>
                </Tooltip>
            ))}
        </Dropdown>
    )
}

function MathPropertySelector(props) {
    const applicableProperties = props.properties.filter(
        ({ value }) => value[0] !== '$' && value !== 'distinct_id' && value !== 'token'
    )

    return (
        <Dropdown
            title={props.mathProperty || 'Select property'}
            titleEmpty="No applicable properties"
            buttonClassName="btn btn-sm btn-light ml-2"
            data-attr={`math-property-selector-${props.index}`}
        >
            {applicableProperties.map(({ value, label }) => (
                <Tooltip
                    placement="right"
                    title={
                        <>
                            Calculate {MATHS[props.math].name.toLowerCase()} from property <code>{label}</code>. Note
                            that only {props.name} occurences where <code>{label}</code> is set and a number will be
                            taken into account.
                        </>
                    }
                    key={`math-property-${value}-${props.index}`}
                >
                    <a
                        href="#"
                        className="dropdown-item"
                        onClick={() => props.onMathPropertySelect(props.index, value)}
                        data-attr={`math-property-${value}-${props.index}`}
                    >
                        {label}
                    </a>
                </Tooltip>
            ))}
        </Dropdown>
    )
}
