import React, { CSSProperties, useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from '../PropertyFilters/propertyFilterLogic'
import '../../../scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { AndOrPropertyFilter, AndOrPropertyGroup, AnyPropertyFilter, PropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { FilterRow } from '../PropertyFilters/components/FilterRow'
import { Button, Col, Row, Select } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import './MatchPropertyFilters.scss'

interface MatchPropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AndOrPropertyFilter | null | PropertyFilter[]
    onChange: (filters: AndOrPropertyFilter) => void
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
    popoverPlacement = null,
    taxonomicPopoverPlacement = undefined,
    taxonomicGroupTypes,
    style = {},
    showNestedArrow = false,
    eventNames = [],
}: MatchPropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey }
    const { filtersWithNew } = useValues(propertyFilterLogic(logicProps))
    const { remove, setFilters, addFilterGroup, addPropertyToGroup, removeFilterGroup } = useActions(
        propertyFilterLogic(logicProps)
    )

    // Update the logic's internal filters when the props change
    useEffect(() => {
        setFilters(propertyFilters ?? [])
    }, [propertyFilters])

    return (
        <>
            {filtersWithNew.groups && (
                <div className="property-filters">
                    <BindLogic logic={propertyFilterLogic} props={logicProps}>
                        {filtersWithNew.type && <AndOrFilterSelect value={filtersWithNew.type} onChange={() => {}} />}
                        {filtersWithNew.groups.map((group: AndOrPropertyGroup, propertyGroupIndex: number) => {
                            return (
                                <>
                                    <div className="mt" style={style} key={propertyGroupIndex}>
                                        <Row justify="space-between" align="middle" className="mb-05">
                                            <AndOrFilterSelect onChange={() => {}} value={group.type} />
                                            <div
                                                style={{
                                                    marginLeft: 8,
                                                    marginRight: 8,
                                                    height: 1,
                                                    background: '#d9d9d9',
                                                    flex: 1,
                                                }}
                                            />
                                            <DeleteOutlined
                                                onClick={() => removeFilterGroup(propertyGroupIndex)}
                                                style={{ fontSize: 16, color: 'var(--primary-alt)' }}
                                            />
                                        </Row>
                                        {group.groups.map((item: AnyPropertyFilter, propertyIndex: number) => (
                                            <FilterRow
                                                key={propertyIndex}
                                                item={item}
                                                index={propertyIndex}
                                                totalCount={group.groups.length - 1} // empty state
                                                filters={group.groups}
                                                orFiltering={true}
                                                pageKey={`${pageKey}-${propertyGroupIndex}-${propertyIndex}`}
                                                showConditionBadge={showConditionBadge}
                                                disablePopover={true}
                                                popoverPlacement={popoverPlacement}
                                                taxonomicPopoverPlacement={taxonomicPopoverPlacement}
                                                showNestedArrow={showNestedArrow}
                                                label={'Add filter group'}
                                                onRemove={() => remove(propertyGroupIndex, propertyIndex)}
                                                filterComponent={(onComplete) => (
                                                    <TaxonomicPropertyFilter
                                                        key={propertyIndex}
                                                        pageKey={`${pageKey}-${propertyGroupIndex}-${propertyIndex}`}
                                                        index={propertyGroupIndex}
                                                        propertyIndex={propertyIndex}
                                                        onComplete={() => {
                                                            onComplete
                                                        }}
                                                        taxonomicGroupTypes={taxonomicGroupTypes}
                                                        eventNames={eventNames}
                                                        disablePopover={true}
                                                        orFiltering={true}
                                                        selectProps={{
                                                            delayBeforeAutoOpen: 150,
                                                            // placement: pageKey === 'trends-filters' ? 'bottomLeft' : undefined,
                                                            placement: undefined,
                                                        }}
                                                    />
                                                )}
                                            />
                                        ))}
                                        {Object.keys(group.groups[group.groups.length - 1]).length > 0 && (
                                            <Button
                                                style={{
                                                    color: 'var(--primary)',
                                                    border: 'none',
                                                    boxShadow: 'none',
                                                    background: '#FAFAF9',
                                                }}
                                                icon={<PlusOutlined />}
                                                onClick={() => addPropertyToGroup(propertyGroupIndex)}
                                            >
                                                Add filter
                                            </Button>
                                        )}
                                    </div>
                                    {propertyGroupIndex !== filtersWithNew?.groups.length - 1 && (
                                        <Row>{group.type}</Row>
                                    )}
                                </>
                            )
                        })}
                    </BindLogic>
                </div>
            )}
            <div>
                <Button
                    style={{
                        color: 'var(--primary)',
                        border: 'none',
                        boxShadow: 'none',
                        marginBottom: '1rem',
                    }}
                    icon={<PlusOutlined />}
                    onClick={() => addFilterGroup()}
                >
                    Add filter group
                </Button>
            </div>
        </>
    )
}

export enum AndOr {
    AND = 'AND',
    OR = 'OR',
}

interface AndOrFilterSelectProps {
    onChange: () => void
    value: string
}

export function AndOrFilterSelect({ onChange, value }: AndOrFilterSelectProps): JSX.Element {
    return (
        <Row align="middle" className="and-or-filter">
            <span className="ml-05">Match</span>
            <Select
                optionLabelProp="label"
                dropdownClassName="and-or-filter-select"
                style={{ marginLeft: 8, marginRight: 8 }}
                defaultValue="all"
                onChange={onChange}
                dropdownMatchSelectWidth={false}
            >
                <Select.Option value={AndOr.AND} label="all" className="condition-option">
                    <Row>
                        <div className={`condition-text ${value === AndOr.AND ? 'selected' : ''}`}>{AndOr.AND}</div>
                        <Col>
                            <div>
                                <b>All filter</b>{' '}
                            </div>
                            <div>All filters must be met (logical and)</div>
                        </Col>
                    </Row>
                </Select.Option>
                <Select.Option value={AndOr.OR} label="any" className="condition-option">
                    <Row>
                        <div className={`condition-text ${value === AndOr.OR ? 'selected' : ''}`}>{AndOr.OR}</div>
                        <Col>
                            <div>
                                <b>Any filter</b>{' '}
                            </div>
                            <div>Any filter can be met (logical or)</div>
                        </Col>
                    </Row>
                </Select.Option>
            </Select>{' '}
            filters in this group
        </Row>
    )
}
