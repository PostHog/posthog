import React from 'react'
import { useActions, useValues } from 'kea'
import { Button, Col, Row, Select } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import {
    ActionFilter as ActionFilterType,
    ActionFilter,
    EntityType,
    EntityTypes,
    FunnelStepRangeEntityFilter,
    PropertyFilter,
    PropertyFilterValue,
    SelectOption,
} from '~/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import {
    CloseSquareOutlined,
    DeleteOutlined,
    DownOutlined,
    EditOutlined,
    FilterOutlined,
    CopyOutlined,
} from '@ant-design/icons'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { BareEntity, entityFilterLogic } from '../entityFilterLogic'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { getEventNamesForAction, pluralize } from 'lib/utils'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import './index.scss'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import clsx from 'clsx'
import { apiValueToMathType, mathsLogic, mathTypeToApiValues } from 'scenes/trends/mathsLogic'
import { GroupsIntroductionOption } from 'lib/introductions/GroupsIntroductionOption'
import { actionsModel } from '~/models/actionsModel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

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
    hideRename?: boolean // Hides the rename option
    onRenameClick?: () => void // Used to open rename modal
    showSeriesIndicator?: boolean // Show series badge
    seriesIndicatorType?: 'alpha' | 'numeric' // Series badge shows A, B, C | 1, 2, 3
    horizontalUI?: boolean
    fullWidth?: boolean
    filterCount: number
    customRowPrefix?:
        | string
        | JSX.Element
        | ((props: {
              filter: ActionFilterType | FunnelStepRangeEntityFilter
              index: number
              onClose: () => void
          }) => JSX.Element) // Custom prefix element to show in each row
    customRowSuffix?:
        | string
        | JSX.Element
        | ((props: {
              filter: ActionFilterType | FunnelStepRangeEntityFilter
              index: number
              onClose: () => void
          }) => JSX.Element) // Custom suffix element to show in each row
    rowClassName?: string
    propertyFilterWrapperClassName?: string
    stripeActionRow?: boolean // Whether or not to alternate the color behind the action rows
    hasBreakdown: boolean // Whether the current graph has a breakdown filter applied
    showNestedArrow?: boolean // Show nested arrows to the left of property filter buttons
    actionsTaxonomicGroupTypes?: TaxonomicFilterGroupType[] // Which tabs to show for actions selector
    propertiesTaxonomicGroupTypes?: TaxonomicFilterGroupType[] // Which tabs to show for property filters
    hideDeleteBtn?: boolean // Choose to hide delete btn. You can use the onClose function passed into customRow{Pre|Suf}fix to render the delete btn anywhere
    disabled?: boolean
    renderRow?: ({
        seriesIndicator,
        prefix,
        filter,
        suffix,
        propertyFiltersButton,
        renameRowButton,
        deleteButton,
        orLabel,
    }: Record<string, JSX.Element | string | undefined>) => JSX.Element // build your own row given these components
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
    hideRename,
    onRenameClick = () => {},
    showSeriesIndicator,
    seriesIndicatorType = 'alpha',
    horizontalUI = false,
    fullWidth = false,
    filterCount,
    customRowPrefix,
    customRowSuffix,
    rowClassName,
    propertyFilterWrapperClassName,
    stripeActionRow = true,
    hasBreakdown,
    showNestedArrow = false,
    hideDeleteBtn = false,
    actionsTaxonomicGroupTypes = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    propertiesTaxonomicGroupTypes,
    disabled = false,
    renderRow,
}: ActionFilterRowProps): JSX.Element {
    const { selectedFilter, entities, entityFilterVisible } = useValues(logic)
    const {
        updateFilter,
        selectFilter,
        updateFilterMath,
        removeLocalFilter,
        updateFilterProperty,
        setEntityFilterVisibility,
        duplicateFilter,
    } = useActions(logic)
    const { numericalPropertyNames } = useValues(propertyDefinitionsModel)
    const { actions } = useValues(actionsModel)
    const { mathDefinitions } = useValues(mathsLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    const visible = typeof filter.order === 'number' ? entityFilterVisible[filter.order] : false

    let entity: BareEntity, name: string | null | undefined, value: PropertyFilterValue
    const { math, math_property: mathProperty, math_group_type_index: mathGroupTypeIndex } = filter

    const onClose = (): void => {
        removeLocalFilter({ ...filter, index })
    }
    const onMathSelect = (_: unknown, selectedMath: string): void => {
        updateFilterMath({
            ...mathTypeToApiValues(selectedMath),
            math_property: mathDefinitions[selectedMath]?.onProperty ? mathProperty ?? '$time' : undefined,
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

    const seriesIndicator =
        seriesIndicatorType === 'numeric' ? (
            <SeriesGlyph style={{ borderColor: 'var(--border)' }}>{index + 1}</SeriesGlyph>
        ) : (
            <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
        )

    const prefix = typeof customRowPrefix === 'function' ? customRowPrefix({ filter, index, onClose }) : customRowPrefix

    const filterElement = (
        <Popup
            overlay={
                <TaxonomicFilter
                    groupType={filter.type as TaxonomicFilterGroupType}
                    value={
                        filter.type === 'actions' && typeof value === 'string' ? parseInt(value) : value || undefined
                    }
                    onChange={(taxonomicGroup, changedValue, item) => {
                        updateFilter({
                            type: taxonomicFilterGroupTypeToEntityType(taxonomicGroup.type) || undefined,
                            id: `${changedValue}`,
                            name: item?.name,
                            index,
                        })
                    }}
                    onClose={() => selectFilter(null)}
                    taxonomicGroupTypes={actionsTaxonomicGroupTypes}
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
                    disabled={disabled}
                    style={{
                        maxWidth: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                    }}
                >
                    <span className="text-overflow" style={{ maxWidth: '100%' }}>
                        <EntityFilterInfo filter={filter} />
                    </span>
                    <DownOutlined style={{ fontSize: 10 }} />
                </Button>
            )}
        </Popup>
    )

    const suffix = typeof customRowSuffix === 'function' ? customRowSuffix({ filter, index, onClose }) : customRowSuffix

    const propertyFiltersButton = (
        <Button
            type="link"
            onClick={() => {
                typeof filter.order === 'number' ? setEntityFilterVisibility(filter.order, !visible) : undefined
            }}
            className={`row-action-btn show-filters${visible ? ' visible' : ''}`}
            data-attr={'show-prop-filter-' + index}
            title="Show filters"
        >
            <FilterOutlined />
            {filter.properties?.length ? pluralize(filter.properties?.length, 'filter') : null}
        </Button>
    )

    const renameRowButton = (
        <Button
            type="link"
            onClick={() => {
                selectFilter(filter)
                onRenameClick()
            }}
            className={`row-action-btn show-rename`}
            data-attr={'show-prop-rename-' + index}
            title="Rename graph series"
        >
            <EditOutlined />
        </Button>
    )

    const duplicateRowButton = (
        <Button
            type="link"
            onClick={() => {
                duplicateFilter(filter)
            }}
            className={`row-action-btn show-duplicabe`}
            data-attr={'show-prop-duplicate-' + index}
            title="Duplicate graph series"
        >
            <CopyOutlined />
        </Button>
    )

    const deleteButton = (
        <Button
            type="link"
            onClick={onClose}
            className="row-action-btn delete"
            data-attr={'delete-prop-filter-' + index}
            title="Delete graph series"
        >
            <DeleteOutlined />
        </Button>
    )

    return (
        <div
            className={clsx({
                'action-row-striped': horizontalUI && stripeActionRow,
                'action-row': !horizontalUI || !stripeActionRow,
                'full-width': fullWidth,
            })}
        >
            {!horizontalUI && index > 0 && showOr && (
                <Row align="middle" style={{ marginTop: 12 }}>
                    {orLabel}
                </Row>
            )}

            <Row gutter={8} align="middle" className={`${!horizontalUI ? 'mt' : ''} ${rowClassName}`} wrap={!fullWidth}>
                {renderRow ? (
                    renderRow({
                        seriesIndicator,
                        prefix,
                        filter: filterElement,
                        suffix,
                        propertyFiltersButton: propertyFiltersButton,
                        renameRowButton,
                        deleteButton,
                        orLabel,
                    })
                ) : (
                    <>
                        {!hideDeleteBtn && horizontalUI && !singleFilter && filterCount > 1 && (
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
                        {showSeriesIndicator && <Col className="action-row-letter">{seriesIndicator}</Col>}
                        {customRowPrefix !== undefined ? (
                            <Col>{prefix}</Col>
                        ) : (
                            <>{horizontalUI && <Col>Showing</Col>}</>
                        )}
                        <Col
                            className="column-filter"
                            style={fullWidth ? {} : { maxWidth: `calc(${hideMathSelector ? '100' : '50'}% - 16px)` }}
                            flex={fullWidth ? 'auto' : undefined}
                        >
                            {filterElement}
                        </Col>
                        {customRowSuffix !== undefined && <Col className="column-row-suffix">{suffix}</Col>}
                        {!hideMathSelector && (
                            <>
                                {horizontalUI && <Col>counted by</Col>}
                                <Col style={{ maxWidth: `calc(50% - 16px${showSeriesIndicator ? ' - 32px' : ''})` }}>
                                    <MathSelector
                                        math={math}
                                        mathGroupTypeIndex={mathGroupTypeIndex}
                                        index={index}
                                        onMathSelect={onMathSelect}
                                        areEventPropertiesNumericalAvailable={!!numericalPropertyNames.length}
                                        style={{ maxWidth: '100%', width: 'initial' }}
                                    />
                                </Col>
                                {mathDefinitions[math || '']?.onProperty && (
                                    <>
                                        {horizontalUI && <Col>on property</Col>}
                                        <Col
                                            style={{
                                                maxWidth: `calc(50% - 16px${showSeriesIndicator ? ' - 32px' : ''})`,
                                            }}
                                        >
                                            <MathPropertySelector
                                                name={name}
                                                math={math}
                                                mathProperty={mathProperty}
                                                index={index}
                                                onMathPropertySelect={onMathPropertySelect}
                                                properties={numericalPropertyNames}
                                                horizontalUI={horizontalUI}
                                                exposeWebPerformance={!!featureFlags[FEATURE_FLAGS.WEB_PERFORMANCE]}
                                            />
                                        </Col>
                                    </>
                                )}
                            </>
                        )}
                        {(horizontalUI || fullWidth) && !hideFilter && <Col>{propertyFiltersButton}</Col>}
                        {(horizontalUI || fullWidth) && !hideRename && <Col>{renameRowButton}</Col>}
                        {(horizontalUI || fullWidth) && !hideFilter && !singleFilter && <Col>{duplicateRowButton}</Col>}
                        {!hideDeleteBtn && !horizontalUI && !singleFilter && (
                            <Col className="column-delete-btn">{deleteButton}</Col>
                        )}
                        {horizontalUI && filterCount > 1 && index < filterCount - 1 && showOr && orLabel}
                    </>
                )}
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
                <div
                    className={
                        propertyFilterWrapperClassName
                            ? `mr property-filter-wrapper ${propertyFilterWrapperClassName}`
                            : 'mr property-filter-wrapper'
                    }
                >
                    <PropertyFilters
                        pageKey={`${index}-${value}-filter`}
                        propertyFilters={filter.properties}
                        onChange={(properties) => updateFilterProperty({ properties, index })}
                        disablePopover={horizontalUI}
                        style={{ marginBottom: 0 }}
                        showNestedArrow={showNestedArrow}
                        taxonomicGroupTypes={propertiesTaxonomicGroupTypes}
                        eventNames={
                            filter.type === TaxonomicFilterGroupType.Events && filter.id
                                ? [String(filter.id)]
                                : filter.type === TaxonomicFilterGroupType.Actions && filter.id
                                ? getEventNamesForAction(parseInt(String(filter.id)), actions)
                                : []
                        }
                    />
                </div>
            )}
        </div>
    )
}

interface MathSelectorProps {
    math?: string
    mathGroupTypeIndex?: number | null
    index: number
    onMathSelect: (index: number, value: any) => any // TODO
    areEventPropertiesNumericalAvailable?: boolean
    style?: React.CSSProperties
}

function MathSelector({
    math,
    mathGroupTypeIndex,
    index,
    onMathSelect,
    areEventPropertiesNumericalAvailable,
    style,
}: MathSelectorProps): JSX.Element {
    const numericalNotice = `This can only be used on properties that have at least one number type occurence in your events.${
        areEventPropertiesNumericalAvailable ? '' : ' None have been found yet!'
    }`
    const { eventMathEntries, propertyMathEntries } = useValues(mathsLogic)

    const math_entries = eventMathEntries

    return (
        <Select
            style={{ width: 150, ...style }}
            value={apiValueToMathType(math, mathGroupTypeIndex)}
            onChange={(value) => onMathSelect(index, value)}
            data-attr={`math-selector-${index}`}
            dropdownMatchSelectWidth={false}
            dropdownStyle={{ maxWidth: 320 }}
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
                {/* :KLUDGE: Select only allows Select.Option as children, so render groups option directly rather than as a child */}
                {GroupsIntroductionOption({ value: '' })}
            </Select.OptGroup>
            <Select.OptGroup key="property aggregates" label="Property aggregation">
                {propertyMathEntries.map(([key, { name, description, onProperty }]) => {
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
    exposeWebPerformance?: boolean
}

function MathPropertySelector(props: MathPropertySelectorProps): JSX.Element {
    const { mathDefinitions } = useValues(mathsLogic)

    function isPropertyApplicable(value: PropertyFilter['value']): boolean {
        const includedProperties = ['$time']
        if (props.exposeWebPerformance) {
            includedProperties.push('$performance_page_loaded')
        }
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
                                Calculate {mathDefinitions[props.math ?? ''].name.toLowerCase()} from property{' '}
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
