import React, { useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import '../../../scenes/actions/Actions.scss'
import { PropertyGroupFilter, FilterLogicalOperator, PropertyGroupFilterValue, FilterType } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Col, Row, Select } from 'antd'
import './PropertyGroupFilters.scss'
import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'
import { PropertyFilters } from '../PropertyFilters/PropertyFilters'
import { GlobalFiltersTitle } from 'scenes/insights/common'
import { IconCopy, IconDelete, IconPlusMini } from '../icons'
import { LemonButton } from '../LemonButton'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'

interface PropertyGroupFilters {
    propertyFilters?: PropertyGroupFilter | null
    onChange: (filters: PropertyGroupFilter) => void
    pageKey: string
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    eventNames?: string[]
    setTestFilters: (filters: Partial<FilterType>) => void
    filters: Partial<FilterType>
}

export function PropertyGroupFilters({
    propertyFilters = null,
    onChange,
    pageKey,
    taxonomicGroupTypes,
    eventNames = [],
    setTestFilters,
    filters,
}: PropertyGroupFilters): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey }
    const { filtersWithNew } = useValues(propertyGroupFilterLogic(logicProps))
    const {
        setFilters,
        addFilterGroup,
        removeFilterGroup,
        setOuterPropertyGroupsType,
        setInnerPropertyGroupType,
        setPropertyFilters,
        duplicateFilterGroup,
    } = useActions(propertyGroupFilterLogic(logicProps))

    // Update the logic's internal filters when the props change
    useEffect(() => {
        setFilters(propertyFilters ?? { type: FilterLogicalOperator.And, values: [] })
    }, [propertyFilters])

    return (
        <>
            {filtersWithNew.values && (
                <div className="property-group-filters">
                    <BindLogic logic={propertyGroupFilterLogic} props={logicProps}>
                        <Row
                            align="middle"
                            justify="space-between"
                            className="pb pr mb"
                            style={{ borderBottom: '1px solid var(--border)' }}
                        >
                            <GlobalFiltersTitle orFiltering={true} />
                            {filtersWithNew.type && filtersWithNew.values.length > 1 && (
                                <AndOrFilterSelect
                                    value={filtersWithNew.type}
                                    onChange={(value) => setOuterPropertyGroupsType(value)}
                                    topLevelFilter={true}
                                />
                            )}
                        </Row>
                        <TestAccountFilter filters={filters} onChange={(testFilters) => setTestFilters(testFilters)} />
                        {filtersWithNew.values?.map((group: PropertyGroupFilterValue, propertyGroupIndex: number) => {
                            return (
                                <>
                                    <div className="property-group" key={propertyGroupIndex}>
                                        <Row justify="space-between" align="middle" className="mb-05">
                                            <AndOrFilterSelect
                                                onChange={(type) => setInnerPropertyGroupType(type, propertyGroupIndex)}
                                                value={group.type}
                                            />
                                            <div
                                                style={{
                                                    marginLeft: 8,
                                                    marginRight: 8,
                                                    height: 1,
                                                    background: '#d9d9d9',
                                                    flex: 1,
                                                }}
                                            />
                                            <LemonButton
                                                icon={<IconCopy />}
                                                type="primary-alt"
                                                onClick={() => duplicateFilterGroup(propertyGroupIndex)}
                                                compact
                                            />
                                            <LemonButton
                                                icon={<IconDelete />}
                                                type="primary-alt"
                                                onClick={() => removeFilterGroup(propertyGroupIndex)}
                                                compact
                                            />
                                        </Row>
                                        <PropertyFilters
                                            orFiltering={true}
                                            propertyFilters={group.values}
                                            style={{ marginBottom: 0 }}
                                            onChange={(properties) => {
                                                setPropertyFilters(properties, propertyGroupIndex)
                                            }}
                                            pageKey={`trends-filters-${propertyGroupIndex}`}
                                            taxonomicGroupTypes={taxonomicGroupTypes}
                                            eventNames={eventNames}
                                            propertyGroupType={group.type}
                                        />
                                    </div>
                                    {propertyGroupIndex !== filtersWithNew.values.length - 1 && (
                                        <div className="text-small primary-alt" style={{ margin: '-0.5rem 0' }}>
                                            <b>{filtersWithNew.type}</b>
                                        </div>
                                    )}
                                </>
                            )
                        })}
                    </BindLogic>
                </div>
            )}
            <LemonButton
                data-attr={`${pageKey}-add-filter-group`}
                className="mb mt"
                type="secondary"
                onClick={() => addFilterGroup()}
                icon={<IconPlusMini color="var(--primary)" />}
                fullWidth
            >
                Add filter group
            </LemonButton>
        </>
    )
}

interface AndOrFilterSelectProps {
    onChange: (type: FilterLogicalOperator) => void
    value: FilterLogicalOperator
    topLevelFilter?: boolean
}

export function AndOrFilterSelect({ onChange, value, topLevelFilter }: AndOrFilterSelectProps): JSX.Element {
    return (
        <Row align="middle" className="and-or-filter">
            <span className="ml-05">Match</span>
            <Select
                optionLabelProp="label"
                dropdownClassName="and-or-filter-select"
                style={{ marginLeft: 8, marginRight: 8 }}
                defaultValue={value || FilterLogicalOperator.And}
                onChange={(type) => onChange(type)}
                dropdownMatchSelectWidth={false}
                placement={topLevelFilter ? 'bottomRight' : 'bottomLeft'}
            >
                <Select.Option value={FilterLogicalOperator.And} label="all" className="condition-option">
                    <Row>
                        <div className={`condition-text ${value === FilterLogicalOperator.And ? 'selected' : ''}`}>
                            {FilterLogicalOperator.And}
                        </div>
                        <Col>
                            <div>
                                <b>All filter</b>{' '}
                            </div>
                            <div>All filters must be met (logical and)</div>
                        </Col>
                    </Row>
                </Select.Option>
                <Select.Option value={FilterLogicalOperator.Or} label="any" className="condition-option">
                    <Row>
                        <div className={`condition-text ${value === FilterLogicalOperator.Or ? 'selected' : ''}`}>
                            {FilterLogicalOperator.Or}
                        </div>
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
