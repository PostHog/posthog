import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { Button, Tooltip, Col, Row, Select } from 'antd'
import { EntityTypes } from '../../trends/trendsLogic'
import { ActionFilterDropdown } from './ActionFilterDropdown'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PROPERTY_MATH_TYPE, EVENT_MATH_TYPE, MATHS } from 'lib/constants'
import { DownOutlined, DeleteOutlined } from '@ant-design/icons'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import './ActionFilterRow.scss'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { propertyDefinitionsLogic } from 'scenes/events/propertyDefinitionsLogic'

const EVENT_MATH_ENTRIES = Object.entries(MATHS).filter(([, item]) => item.type == EVENT_MATH_TYPE)
const PROPERTY_MATH_ENTRIES = Object.entries(MATHS).filter(([, item]) => item.type == PROPERTY_MATH_TYPE)

const determineFilterLabel = (visible, filter) => {
    if (visible) {
        return 'Hide filters'
    }
    if (filter.properties && Object.keys(filter.properties).length > 0) {
        return `${Object.keys(filter.properties).length} filter${
            Object.keys(filter.properties).length === 1 ? '' : 's'
        }`
    }
    return 'Add filters'
}

export function ActionFilterRow({
    logic,
    filter,
    index,
    hideMathSelector,
    hidePropertySelector,
    singleFilter,
    showOr,
    letter,
}) {
    const node = useRef()
    const { selectedFilter, entities, entityFilterVisible } = useValues(logic)
    const {
        selectFilter,
        updateFilterMath,
        removeLocalFilter,
        updateFilterProperty,
        setEntityFilterVisibility,
    } = useActions(logic)
    const { propertyNames, numericalPropertyNames } = useValues(propertyDefinitionsLogic)

    const visible = entityFilterVisible[filter.order]

    let entity, name, value
    let math = filter.math
    let mathProperty = filter.math_property

    const onClose = () => {
        removeLocalFilter({ value: filter.id, type: filter.type, index })
    }
    const onMathSelect = (_, selectedMath) => {
        updateFilterMath({
            math: selectedMath,
            math_property: MATHS[selectedMath]?.onProperty ? mathProperty : undefined,
            onProperty: MATHS[selectedMath]?.onProperty,
            value: filter.id,
            type: filter.type,
            index: index,
        })
    }
    const onMathPropertySelect = (_, selectedMathProperty) => {
        updateFilterMath({
            math: filter.math,
            math_property: selectedMathProperty,
            value: filter.id,
            type: filter.type,
            index: index,
        })
    }

    const dropDownCondition = () =>
        selectedFilter && selectedFilter.type === filter.type && selectedFilter.index === index

    const onClick = () => {
        if (selectedFilter && selectedFilter.type === filter.type && selectedFilter.index === index) {
            selectFilter(null)
        } else {
            selectFilter({ filter, type: filter.type, index })
        }
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
        <div>
            {showOr && (
                <Row align="center">
                    {index > 0 && (
                        <div className="stateful-badge mc-main or width-locked" style={{ marginTop: 12 }}>
                            OR
                        </div>
                    )}
                </Row>
            )}
            <Row gutter={8} className="mt">
                {letter && (
                    <Col className="action-row-letter">
                        <span>{letter}</span>
                    </Col>
                )}
                <Col style={{ maxWidth: `calc(${hideMathSelector ? '100' : '50'}% - 16px)` }}>
                    <Button
                        data-attr={'trend-element-subject-' + index}
                        ref={node}
                        onClick={onClick}
                        style={{ maxWidth: '100%', display: 'flex', alignItems: 'center' }}
                    >
                        <span className="text-overflow" style={{ maxWidth: '100%' }}>
                            <PropertyKeyInfo value={name || 'Select action'} />
                        </span>
                        <DownOutlined style={{ fontSize: 10 }} />
                    </Button>
                    <ActionFilterDropdown
                        open={dropDownCondition()}
                        logic={logic}
                        openButtonRef={node}
                        onClose={() => selectFilter(null)}
                    />
                </Col>
                <Col style={{ maxWidth: `calc(50% - 16px${letter ? ' - 32px' : ''})` }}>
                    {!hideMathSelector && (
                        <MathSelector
                            math={math}
                            index={index}
                            onMathSelect={onMathSelect}
                            areEventPropertiesNumericalAvailable={!!numericalPropertyNames.length}
                            style={{ maxWidth: '100%', width: 'initial' }}
                        />
                    )}
                </Col>
                {!singleFilter && (
                    <Col>
                        <Button
                            type="link"
                            onClick={onClose}
                            style={{
                                padding: 0,
                                paddingLeft: 8,
                            }}
                        >
                            <DeleteOutlined />
                        </Button>
                    </Col>
                )}
            </Row>
            {!hideMathSelector && MATHS[math]?.onProperty && (
                <MathPropertySelector
                    name={name}
                    math={math}
                    mathProperty={mathProperty}
                    index={index}
                    onMathPropertySelect={onMathPropertySelect}
                    properties={numericalPropertyNames}
                />
            )}
            {(!hidePropertySelector || (filter.properties && filter.properties.length > 0)) && (
                <div style={{ paddingTop: 6 }}>
                    <span style={{ color: '#C4C4C4', fontSize: 18, paddingLeft: 6, paddingRight: 2 }}>&#8627;</span>
                    <Button
                        className="ant-btn-md"
                        onClick={() => setEntityFilterVisibility(filter.order, !visible)}
                        data-attr={'show-prop-filter-' + index}
                    >
                        {determineFilterLabel(visible, filter)}
                    </Button>
                </div>
            )}

            {visible && (
                <div className="ml">
                    <PropertyFilters
                        pageKey={`${index}-${value}-filter`}
                        properties={propertyNames}
                        propertyFilters={filter.properties}
                        onChange={(properties) => updateFilterProperty({ properties, index })}
                        style={{ marginBottom: 0 }}
                    />
                </div>
            )}
        </div>
    )
}

function MathSelector({ math, index, onMathSelect, areEventPropertiesNumericalAvailable, style }) {
    const numericalNotice = `This can only be used on properties that have at least one number type occurence in your events.${
        areEventPropertiesNumericalAvailable ? '' : ' None have been found yet!'
    }`
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    let math_entries = EVENT_MATH_ENTRIES

    if (!featureFlags['3638-trailing-wau-mau'] || !preflight?.ee_enabled) {
        math_entries = math_entries.filter((item) => item[0] !== 'weekly_active' && item[0] !== 'monthly_active')
    }

    return (
        <Select
            style={{ width: 150, ...style }}
            value={math || 'total'}
            onChange={(value) => onMathSelect(index, value)}
            data-attr={`math-selector-${index}`}
        >
            <Select.OptGroup key="event aggregates" label="Event aggregation">
                {math_entries.map(([key, { name, description, onProperty }]) => {
                    const disabled = onProperty && !areEventPropertiesNumericalAvailable
                    return (
                        <Select.Option key={key} value={key} data-attr={`math-${key}-${index}`} disabled={disabled}>
                            <Tooltip
                                title={
                                    onProperty ? (
                                        <>
                                            {description}
                                            <br />
                                            {numericalNotice}
                                        </>
                                    ) : (
                                        description
                                    )
                                }
                                placement="right"
                            >
                                <div
                                    style={{
                                        height: '100%',
                                        width: '100%',
                                        paddingRight: 8,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                    }}
                                >
                                    {name}
                                </div>
                            </Tooltip>
                        </Select.Option>
                    )
                })}
            </Select.OptGroup>
            <Select.OptGroup key="property aggregates" label="Property aggregation">
                {PROPERTY_MATH_ENTRIES.map(([key, { name, description, onProperty }]) => {
                    const disabled = onProperty && !areEventPropertiesNumericalAvailable
                    return (
                        <Select.Option key={key} value={key} data-attr={`math-${key}-${index}`} disabled={disabled}>
                            <Tooltip
                                title={
                                    onProperty ? (
                                        <>
                                            {description}
                                            <br />
                                            {numericalNotice}
                                        </>
                                    ) : (
                                        description
                                    )
                                }
                                placement="right"
                            >
                                <div style={{ height: '100%', width: '100%' }}>{name}</div>
                            </Tooltip>
                        </Select.Option>
                    )
                })}
            </Select.OptGroup>
        </Select>
    )
}

function MathPropertySelector(props) {
    const applicableProperties = props.properties
        .filter(({ value }) => (value[0] !== '$' || value === '$time') && value !== 'distinct_id' && value !== 'token')
        .sort((a, b) => (a.value + '').localeCompare(b.value))

    return (
        <SelectGradientOverflow
            showSearch
            style={{ width: 150 }}
            onChange={(_, payload) => props.onMathPropertySelect(props.index, payload && payload.value)}
            className="property-select"
            value={props.mathProperty}
            data-attr="math-property-select"
            dropdownMatchSelectWidth={350}
            placeholder={'Select property'}
        >
            {applicableProperties.map(({ value, label }) => (
                <Select.Option
                    key={`math-property-${value}-${props.index}`}
                    value={value}
                    data-attr={`math-property-${value}-${props.index}`}
                >
                    <Tooltip
                        title={
                            <>
                                Calculate {MATHS[props.math].name.toLowerCase()} from property <code>{label}</code>.
                                Note that only {props.name} occurences where <code>{label}</code> is set and a number
                                will be taken into account.
                            </>
                        }
                        placement="right"
                        overlayStyle={{ zIndex: 9999999999 }}
                    >
                        {label}
                    </Tooltip>
                </Select.Option>
            ))}
        </SelectGradientOverflow>
    )
}
