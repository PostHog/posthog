import React, { CSSProperties, useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import '../../../scenes/actions/Actions.scss'
import { PropertyGroupFilter, FilterLogicalOperator, PropertyGroupFilterValue } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Col, Row, Select } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import './PropertyGroupFilters.scss'
import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'
import { PropertyFilters } from '../PropertyFilters/PropertyFilters'
import { GlobalFiltersTitle } from 'scenes/insights/common'
import { IconDelete, IconPlus } from '../icons'
import { LemonButton } from '../LemonButton'

interface PropertyGroupFilters {
    propertyFilters?: PropertyGroupFilter | null
    onChange: (filters: PropertyGroupFilter) => void
    pageKey: string
    style?: CSSProperties
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    eventNames?: string[]
}

export function PropertyGroupFilters({
    propertyFilters = null,
    onChange,
    pageKey,
    taxonomicGroupTypes,
    style = {},
    eventNames = [],
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
                        {filtersWithNew.values?.map((group: PropertyGroupFilterValue, propertyGroupIndex: number) => {
                            return (
                                <>
                                    <div className="mt mb" style={style} key={propertyGroupIndex}>
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
                                                icon={<CopyOutlined style={{ fontSize: '1rem' }} />}
                                                type="primary-alt"
                                                onClick={() => duplicateFilterGroup(propertyGroupIndex)}
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
                                        <Row className="text-small primary-alt">
                                            <b>{filtersWithNew.type}</b>
                                        </Row>
                                    )}
                                </>
                            )
                        })}
                    </BindLogic>
                </div>
            )}
            <div>
                {filtersWithNew.values.length > 1 ? (
                    <LemonButton
                        data-attr={`${pageKey}-add-filter-group`}
                        className="mb full-width"
                        type="secondary"
                        style={{ fontWeight: 400 }}
                        onClick={() => addFilterGroup()}
                    >
                        <IconPlus className="mr-05" /> Add filter group
                    </LemonButton>
                ) : (
                    <LemonButton
                        data-attr={`${pageKey}-add-filter-group`}
                        onClick={() => addFilterGroup()}
                        className="mb"
                        style={{
                            border: 'none',
                            background: 'none',
                            fontWeight: 400,
                        }}
                        type="default"
                    >
                        <IconPlus className="mr-05" /> Add filter group
                    </LemonButton>
                )}
            </div>
        </>
    )
}

interface AndOrFilterSelectProps {
    onChange: (type: FilterLogicalOperator) => void
    value: string
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
                defaultValue={FilterLogicalOperator.And}
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
