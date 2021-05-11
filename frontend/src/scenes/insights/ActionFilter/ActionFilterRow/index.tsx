import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { Button, Tooltip, Col, Row, Select } from 'antd'
import { ActionFilter, EntityTypes, PropertyFilter, SelectOption } from '~/types'
import { ActionFilterDropdown } from './ActionFilterDropdown'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PROPERTY_MATH_TYPE, EVENT_MATH_TYPE, MATHS } from 'lib/constants'
import { DownOutlined, DeleteOutlined, FilterOutlined } from '@ant-design/icons'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { BareEntity, entityFilterLogic } from '../entityFilterLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { propertyDefinitionsLogic } from 'scenes/events/propertyDefinitionsLogic'
import { pluralize } from 'lib/utils'
import './index.scss'

const EVENT_MATH_ENTRIES = Object.entries(MATHS).filter(([, item]) => item.type == EVENT_MATH_TYPE)
const PROPERTY_MATH_ENTRIES = Object.entries(MATHS).filter(([, item]) => item.type == PROPERTY_MATH_TYPE)

const determineFilterLabel = (visible: boolean, filter: Partial<ActionFilter>): string => {
    if (visible) {
        return 'Hide filters'
    }
    if (filter.properties && Object.keys(filter.properties).length > 0) {
        return pluralize(filter.properties?.length, 'filter')
    }
    return 'Add filters'
}

interface ActionFilterRowProps {
    logic: typeof entityFilterLogic
    filter: ActionFilter
    index: number
    hideMathSelector?: boolean
    hidePropertySelector?: boolean
    singleFilter?: boolean
    showOr?: boolean
    letter?: string | null
    horizontalUI?: boolean
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
    horizontalUI = false,
}: ActionFilterRowProps): JSX.Element {
    const node = useRef<HTMLElement>(null)
    const { selectedFilter, entities, entityFilterVisible } = useValues(logic)
    const {
        selectFilter,
        updateFilterMath,
        removeLocalFilter,
        updateFilterProperty,
        setEntityFilterVisibility,
    } = useActions(logic)
    const { numericalPropertyNames } = useValues(propertyDefinitionsLogic)

    const visible = typeof filter.order === 'number' ? entityFilterVisible[filter.order] : false

    let entity, name, value
    const { math, math_property: mathProperty } = filter

    const onClose = (): void => {
        removeLocalFilter({ ...filter, index })
    }
    const onMathSelect = (_: unknown, selectedMath: string): void => {
        updateFilterMath({
            math: selectedMath,
            math_property: MATHS[selectedMath]?.onProperty ? mathProperty : undefined,
            type: filter.type,
            index,
        })
    }
    const onMathPropertySelect = (_: unknown, property: string): void => {
        updateFilterMath({
            ...filter,
            math_property: property,
            index,
        })
    }

    const dropDownCondition = Boolean(
        selectedFilter && selectedFilter?.type === filter.type && selectedFilter?.index === index
    )

    const separatorWord = math === 'dau' ? 'who did' : 'of' // Separator between property and value.

    const onClick = (): void => {
        if (dropDownCondition) {
            selectFilter(null)
        } else {
            selectFilter({ ...filter, index })
        }
    }

    if (filter.type === EntityTypes.NEW_ENTITY) {
        name = null
        value = null
    } else {
        entity = (entities[filter.type] as BareEntity[])?.filter((action) => action.id === filter.id)[0] || {}
        name = entity.name || filter.name
        value = entity.id || filter.id
    }

    return (
        <div className={horizontalUI ? 'action-row-striped' : ''}>
            {showOr && (
                <Row align="middle">
                    {index > 0 && (
                        <div className="stateful-badge mc-main or width-locked" style={{ marginTop: 12 }}>
                            OR
                        </div>
                    )}
                </Row>
            )}
            <Row gutter={8} align="middle" className={!horizontalUI ? 'mt' : ''}>
                {letter && (
                    <Col className="action-row-letter">
                        <span>{letter}</span>
                    </Col>
                )}
                {horizontalUI && (
                    <>
                        <Col>Showing</Col>
                        {!hideMathSelector && (
                            <>
                                <Col style={{ maxWidth: `calc(50% - 16px${letter ? ' - 32px' : ''})` }}>
                                    <MathSelector
                                        math={math}
                                        index={index}
                                        onMathSelect={onMathSelect}
                                        areEventPropertiesNumericalAvailable={!!numericalPropertyNames.length}
                                        style={{ maxWidth: '100%', width: 'initial' }}
                                    />
                                </Col>
                                {MATHS[math || '']?.onProperty && (
                                    <>
                                        <Col>of</Col>
                                        <Col style={{ maxWidth: `calc(50% - 16px${letter ? ' - 32px' : ''})` }}>
                                            <MathPropertySelector
                                                name={name}
                                                math={math}
                                                mathProperty={mathProperty}
                                                index={index}
                                                onMathPropertySelect={onMathPropertySelect}
                                                properties={numericalPropertyNames}
                                                horizontalUI={horizontalUI}
                                            />
                                        </Col>
                                    </>
                                )}
                            </>
                        )}
                        <Col>{separatorWord}</Col>
                    </>
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
                        open={dropDownCondition}
                        logic={logic}
                        openButtonRef={node}
                        onClose={() => selectFilter(null)}
                    />
                </Col>
                {!horizontalUI && (
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
                )}
                {horizontalUI && (
                    <Col>
                        <Button
                            type="link"
                            onClick={() => {
                                typeof filter.order === 'number'
                                    ? setEntityFilterVisibility(filter.order, !visible)
                                    : undefined
                            }}
                            className={`row-action-btn show-filters ${visible ? 'visible' : ''}`}
                            data-attr={'show-prop-filter-' + index}
                            title="Show filters"
                        >
                            <FilterOutlined />
                            {filter.properties?.length ? pluralize(filter.properties?.length, 'filter') : null}
                        </Button>
                    </Col>
                )}
                {!singleFilter && (
                    <Col>
                        <Button
                            type="link"
                            onClick={onClose}
                            className="row-action-btn delete"
                            data-attr={'delete-prop-filter-' + index}
                            title="Delete graph series"
                        >
                            <DeleteOutlined />
                        </Button>
                    </Col>
                )}
            </Row>
            {!horizontalUI && !hideMathSelector && MATHS[math || '']?.onProperty && (
                <Row align="middle">
                    <MathPropertySelector
                        name={name}
                        math={math}
                        mathProperty={mathProperty}
                        index={index}
                        onMathPropertySelect={onMathPropertySelect}
                        properties={numericalPropertyNames}
                    />
                </Row>
            )}
            {(!hidePropertySelector || (filter.properties && filter.properties.length > 0)) && !horizontalUI && (
                <div style={{ paddingTop: 6 }}>
                    <span style={{ color: '#C4C4C4', fontSize: 18, paddingLeft: 6, paddingRight: 2 }}>&#8627;</span>
                    <Button
                        className="ant-btn-md"
                        onClick={() =>
                            typeof filter.order === 'number'
                                ? setEntityFilterVisibility(filter.order, !visible)
                                : undefined
                        }
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
                        propertyFilters={filter.properties}
                        onChange={(properties: PropertyFilter[]) => updateFilterProperty({ properties, index })}
                        disablePopover={horizontalUI}
                        style={{ marginBottom: 0 }}
                    />
                </div>
            )}
        </div>
    )
}

interface MathSelectorProps {
    math?: string
    index: number
    onMathSelect: (index: number, value: any) => any // TODO
    areEventPropertiesNumericalAvailable?: boolean
    style?: React.CSSProperties
}

function MathSelector({
    math,
    index,
    onMathSelect,
    areEventPropertiesNumericalAvailable,
    style,
}: MathSelectorProps): JSX.Element {
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
            dropdownMatchSelectWidth={false}
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

interface MathPropertySelectorProps {
    name: string | null
    math?: string
    mathProperty?: string
    index: number
    onMathPropertySelect: (index: number, value: string) => any
    properties: SelectOption[]
    horizontalUI?: boolean
}

function MathPropertySelector(props: MathPropertySelectorProps): JSX.Element {
    function isPropertyApplicable(value: PropertyFilter['value']): boolean {
        const includedProperties = ['$time']
        const excludedProperties = ['distinct_id', 'token']
        if (typeof value !== 'string' || !value || excludedProperties.includes(value)) {
            return false
        }
        return value[0] !== '$' || includedProperties.includes(value)
    }
    const applicableProperties = props.properties
        .filter(({ value }) => isPropertyApplicable(value))
        .sort((a, b) => (a.value + '').localeCompare(b.value + ''))

    return (
        <SelectGradientOverflow
            showSearch
            className={`property-select ${props.horizontalUI ? 'horizontal-ui' : ''}`}
            onChange={(_: string, payload) => {
                props.onMathPropertySelect(props.index, (payload as SelectOption)?.value)
            }}
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
                                Calculate {MATHS[props.math ?? ''].name.toLowerCase()} from property{' '}
                                <code>{label}</code>. Note that only {props.name} occurences where <code>{label}</code>{' '}
                                is set with a numeric value will be taken into account.
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
