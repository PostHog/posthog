import React, { CSSProperties, useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from '../PropertyFilters/propertyFilterLogic'
import '../../../scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { AnyPropertyFilter, InsightType, PropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { FilterRow } from '../PropertyFilters/components/FilterRow'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { Button, Col, Row, Select } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import './MatchPropertyFilters.scss'

interface MatchPropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: PropertyFilter[]) => void
    pageKey: string
    showConditionBadge?: boolean
    disablePopover?: boolean
    popoverPlacement?: TooltipPlacement | null
    taxonomicPopoverPlacement?: Placement
    style?: CSSProperties
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    showNestedArrow?: boolean
    eventNames?: string[]
}

export function MatchPropertyFilters({
    propertyFilters = null,
    onChange,
    pageKey,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    popoverPlacement = null,
    taxonomicPopoverPlacement = undefined,
    taxonomicGroupTypes,
    style = {},
    showNestedArrow = false,
    eventNames = [],
}: MatchPropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey }
    const { filtersWithNew, andOrFilters } = useValues(propertyFilterLogic(logicProps))
    const { remove, setFilters, addFilterGroup, addPropertyToGroup } = useActions(propertyFilterLogic(logicProps))

    // Update the logic's internal filters when the props change
    useEffect(() => {
        setFilters(propertyFilters ?? [])
    }, [propertyFilters])

    console.log('and or filters', andOrFilters.property_groups)

    return (
        <>
            {andOrFilters.property_groups?.properties && <div className="property-filters">
                <BindLogic logic={propertyFilterLogic} props={logicProps}>
                    {andOrFilters.property_groups?.type && <AndOrFilterSelect value={andOrFilters.property_groups?.type} onChange={() => { }} />}
                    {andOrFilters.property_groups.properties.map((property, idx) => {
                        return (
                            <>
                                <div className="mt" style={style}>
                                    <AndOrFilterSelect onChange={() => { }} value={property.type} />
                                    {property.properties.map((item, index) =>
                                        <FilterRow
                                            key={index}
                                            item={item}
                                            index={index}
                                            totalCount={property.properties.length - 1} // empty state
                                            filters={property.properties}
                                            pageKey={`${pageKey}-${idx}`}
                                            showConditionBadge={showConditionBadge}
                                            disablePopover={true}
                                            popoverPlacement={popoverPlacement}
                                            taxonomicPopoverPlacement={taxonomicPopoverPlacement}
                                            showNestedArrow={showNestedArrow}
                                            label={'Add filter group'}
                                            onRemove={remove}
                                            filterComponent={(onComplete) => (
                                                <TaxonomicPropertyFilter
                                                    key={index}
                                                    pageKey={`${pageKey}-${idx}`}
                                                    index={index}
                                                    onComplete={() => {
                                                        onComplete
                                                    }
                                                    }
                                                    taxonomicGroupTypes={taxonomicGroupTypes}
                                                    eventNames={eventNames}
                                                    disablePopover={true}
                                                    orFiltering={true}
                                                    selectProps={{
                                                        delayBeforeAutoOpen: 150,
                                                        // placement: pageKey === 'trends-filters' ? 'bottomLeft' : undefined,
                                                        placement: undefined
                                                    }}
                                                />
                                            )}
                                        />
                                    )}
                                </div>
                                {(idx !== andOrFilters?.property_groups?.properties.length - 1) && <Row>
                                    {property.type}
                                </Row>}
                            </>
                        )
                    })}
                </BindLogic>
            </div>}
            <div>
                <Button
                    style={{
                        color: 'var(--primary)',
                        border: 'none',
                        boxShadow: 'none',
                        marginBottom: '1rem',
                    }}
                    icon={<PlusOutlined />}
                    onClick={() => { addFilterGroup() }}
                >
                    Add filter group
                </Button>
            </div>
        </>
    )
}

export enum AndOr {
    AND = "AND",
    OR = "OR"
}

interface AndOrFilterSelectProps {
    onChange: () => void
    value: string
}

export function AndOrFilterSelect({ onChange, value }: AndOrFilterSelectProps): JSX.Element {
    return (
        <Row align="middle" className="and-or-filter">
            <span className="ml-05">Match</span>
            <Select optionLabelProp='label' dropdownClassName="and-or-filter-select" style={{ marginLeft: 8, marginRight: 8 }} defaultValue="all" onChange={onChange} dropdownMatchSelectWidth={false}>
                <Select.Option value={AndOr.AND} label="all" className='condition-option'>
                    <Row>
                        <div className={`condition-text ${value === AndOr.AND ? 'selected' : ''}`}>{AndOr.AND}</div>
                        <Col>
                            <div><b>All filter</b> </div>
                            <div>All filters must be met (logical and)</div>

                        </Col>
                    </Row>
                </Select.Option>
                <Select.Option value={AndOr.OR} label="any" className="condition-option">
                    <Row>
                        <div className={`condition-text ${value === AndOr.OR ? 'selected' : ''}`}>{AndOr.OR}</div>
                        <Col>
                            <div><b>Any filter</b> </div>
                            <div>Any filter can be met (logical or)</div>

                        </Col>
                    </Row>
                </Select.Option>
            </Select> filters in this group
        </Row>
    )
}
