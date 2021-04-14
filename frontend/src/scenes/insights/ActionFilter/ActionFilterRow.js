import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { Button, Col, Row } from 'antd'
import { EntityTypes } from '../../trends/trendsLogic'
import { ActionFilterDropdown } from './ActionFilterDropdown'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { MATHS } from 'lib/constants'
import { DownOutlined, DeleteOutlined } from '@ant-design/icons'
import './ActionFilterRow.scss'
import { teamLogic } from 'scenes/teamLogic'
import { MathSelector } from './MathSelector'
import { MathPropertySelector } from './MathPropertySelector'

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
    const { eventProperties, eventPropertiesNumerical } = useValues(teamLogic)

    const visible = entityFilterVisible[filter.order]

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
        <div className="action-filter-row">
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
                            {name || 'Select action'}
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
                            areEventPropertiesNumericalAvailable={
                                eventPropertiesNumerical && eventPropertiesNumerical.length > 0
                            }
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
                    properties={eventPropertiesNumerical}
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
                        buttonStyle={{
                            maxWidth: 'calc(100% - 24px)', // 24px is padding on .ant-card-body
                        }}
                        pageKey={`${index}-${value}-filter`}
                        properties={eventProperties}
                        propertyFilters={filter.properties}
                        onChange={(properties) => updateFilterProperty({ properties, index })}
                        style={{ marginBottom: 0 }}
                    />
                </div>
            )}
        </div>
    )
}
