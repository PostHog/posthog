import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { Button, Col, Row, Select, Tooltip } from 'antd'
import { ActionFilter, EntityType, EntityTypes, PropertyFilter, PropertyFilterValue, SelectOption } from '~/types'
import { ActionFilterDropdown } from './ActionFilterDropdown'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { EVENT_MATH_TYPE, FEATURE_FLAGS, MATHS, PROPERTY_MATH_TYPE } from 'lib/constants'
import { CloseSquareOutlined, DeleteOutlined, DownOutlined, FilterOutlined } from '@ant-design/icons'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { BareEntity, entityFilterLogic } from '../entityFilterLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { pluralize } from 'lib/utils'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import './index.scss'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

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

export interface ActionFilterRowProps {
    logic: typeof entityFilterLogic
    filter: ActionFilter
    index: number
    hideMathSelector?: boolean
    hidePropertySelector?: boolean // DEPRECATED: Out of use in the new horizontal UI
    singleFilter?: boolean
    showOr?: boolean
    hideFilter?: boolean // Hides the local filter options
    showSeriesIndicator?: boolean // Show series badge
    seriesIndicatorType?: 'alpha' | 'numeric' // Series badge shows A, B, C | 1, 2, 3
    horizontalUI?: boolean
    fullWidth?: boolean
    filterCount: number
    customRowPrefix?: string | JSX.Element // Custom prefix element to show in each row
    hasBreakdown: boolean // Whether the current graph has a breakdown filter applied
    showNestedArrow?: boolean // Show nested arrows to the left of property filter buttons
}

export function ActionFilterRow({
    logic,
    filter,
    index,
    hideMathSelector,
    hidePropertySelector,
    singleFilter,
    showOr,
    hideFilter,
    showSeriesIndicator,
    seriesIndicatorType = 'alpha',
    horizontalUI = false,
    fullWidth = false,
    filterCount,
    customRowPrefix,
    hasBreakdown,
    showNestedArrow = false,
}: ActionFilterRowProps): JSX.Element {
    const node = useRef<HTMLElement>(null)
    const { selectedFilter, entities, entityFilterVisible } = useValues(logic)
    const {
        updateFilter,
        selectFilter,
        updateFilterMath,
        removeLocalFilter,
        updateFilterProperty,
        setEntityFilterVisibility,
    } = useActions(logic)
    const { numericalPropertyNames } = useValues(propertyDefinitionsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    const visible = typeof filter.order === 'number' ? entityFilterVisible[filter.order] : false

    let entity: BareEntity, name: string | null | undefined, value: PropertyFilterValue
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

    const orLabel = <div className="stateful-badge or width-locked">OR</div>

    return (
        <div className={`${horizontalUI ? 'action-row-striped' : 'action-row'} ${fullWidth ? 'full-width' : ''}`}>
            {!horizontalUI && index > 0 && showOr && (
                <Row align="middle" style={{ marginTop: 12 }}>
                    {orLabel}
                </Row>
            )}

            <Row gutter={8} align="middle" className={!horizontalUI ? 'mt' : ''} wrap={!fullWidth}>
                {horizontalUI && !singleFilter && filterCount > 1 && (
                    <Col>
                        <Button
                            type="link"
                            onClick={onClose}
                            className="row-action-btn delete"
                            title="Remove graph series"
                            danger
                            icon={<CloseSquareOutlined />}
                        />
                    </Col>
                )}
                {showSeriesIndicator && (
                    <Col className="action-row-letter">
                        {seriesIndicatorType === 'numeric' ? (
                            <SeriesGlyph style={{ borderColor: 'var(--border)' }}>{index + 1}</SeriesGlyph>
                        ) : (
                            <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
                        )}
                    </Col>
                )}
                {customRowPrefix ? <Col>{customRowPrefix}</Col> : <>{horizontalUI && <Col>Showing</Col>}</>}
                <Col
                    style={fullWidth ? {} : { maxWidth: `calc(${hideMathSelector ? '100' : '50'}% - 16px)` }}
                    flex={fullWidth ? 'auto' : undefined}
                >
                    {featureFlags[FEATURE_FLAGS.TAXONOMIC_PROPERTY_FILTER] ? (
                        <Popup
                            overlay={
                                <TaxonomicFilter
                                    groupType={filter.type as TaxonomicFilterGroupType}
                                    value={
                                        filter.type === 'actions' && typeof value === 'string'
                                            ? parseInt(value)
                                            : value || undefined
                                    }
                                    onChange={(groupType, changedValue, item) => {
                                        updateFilter({
                                            type: taxonomicFilterGroupTypeToEntityType(groupType) || undefined,
                                            id: `${changedValue}`,
                                            name: item?.name,
                                            index,
                                        })
                                    }}
                                    onClose={() => selectFilter(null)}
                                    groupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                                />
                            }
                            visible={dropDownCondition}
                            onClickOutside={() => selectFilter(null)}
                        >
                            {({ setRef }) => (
                                <Button
                                    data-attr={'trend-element-subject-' + index}
                                    onClick={onClick}
                                    block={fullWidth}
                                    ref={setRef}
                                    style={{
                                        maxWidth: '100%',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                    }}
                                >
                                    <span className="text-overflow" style={{ maxWidth: '100%' }}>
                                        <PropertyKeyInfo value={name || 'Select action'} disablePopover />
                                    </span>
                                    <DownOutlined style={{ fontSize: 10 }} />
                                </Button>
                            )}
                        </Popup>
                    ) : (
                        <>
                            <Button
                                data-attr={'trend-element-subject-' + index}
                                ref={node}
                                onClick={onClick}
                                block={fullWidth}
                                style={{
                                    maxWidth: '100%',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                }}
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
                        </>
                    )}
                </Col>
                {!hideMathSelector && (
                    <>
                        {horizontalUI && <Col>counted by</Col>}
                        <Col style={{ maxWidth: `calc(50% - 16px${showSeriesIndicator ? ' - 32px' : ''})` }}>
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
                                {horizontalUI && <Col>on property</Col>}
                                <Col style={{ maxWidth: `calc(50% - 16px${showSeriesIndicator ? ' - 32px' : ''})` }}>
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
                {(horizontalUI || fullWidth) && !hideFilter && (
                    <Col>
                        <Button
                            type="link"
                            onClick={() => {
                                typeof filter.order === 'number'
                                    ? setEntityFilterVisibility(filter.order, !visible)
                                    : undefined
                            }}
                            className={`row-action-btn show-filters${visible ? ' visible' : ''}`}
                            data-attr={'show-prop-filter-' + index}
                            title="Show filters"
                        >
                            <FilterOutlined />
                            {filter.properties?.length ? pluralize(filter.properties?.length, 'filter') : null}
                        </Button>
                    </Col>
                )}
                {!horizontalUI && !singleFilter && (
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
                {horizontalUI && filterCount > 1 && index < filterCount - 1 && showOr && orLabel}
            </Row>
            {(!hidePropertySelector || (filter.properties && filter.properties.length > 0)) &&
                !horizontalUI &&
                !fullWidth && (
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
                <div className="mr property-filter-wrapper">
                    <PropertyFilters
                        pageKey={`${index}-${value}-filter`}
                        propertyFilters={filter.properties}
                        onChange={(properties) => updateFilterProperty({ properties, index })}
                        disablePopover={horizontalUI}
                        style={{ marginBottom: 0 }}
                        showNestedArrow={showNestedArrow}
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

    if (!featureFlags[FEATURE_FLAGS.TRAILING_WAU_MAU] || !preflight?.is_clickhouse_enabled) {
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

const taxonomicFilterGroupTypeToEntityTypeMapping: Partial<Record<TaxonomicFilterGroupType, EntityTypes>> = {
    [TaxonomicFilterGroupType.Events]: EntityTypes.EVENTS,
    [TaxonomicFilterGroupType.Actions]: EntityTypes.ACTIONS,
}

export function taxonomicFilterGroupTypeToEntityType(
    taxonomicFilterGroupType: TaxonomicFilterGroupType
): EntityType | null {
    return taxonomicFilterGroupTypeToEntityTypeMapping[taxonomicFilterGroupType] || null
}
