import React, { CSSProperties, useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import '../../../scenes/actions/Actions.scss'
import { AndOrPropertyFilter, AndOrPropertyGroup } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Button, Col, Row, Select } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import './PropertyGroupFilters.scss'
import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'
import { PropertyFilters } from '../PropertyFilters/PropertyFilters'
import { GlobalFiltersTitle } from 'scenes/insights/common'

interface PropertyGroupFilters {
    propertyFilters?: AndOrPropertyFilter | null
    onChange: (filters: AndOrPropertyFilter) => void
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
        setPropertyGroupsType,
        setPropertyGroupType,
        setPropertyFilters,
    } = useActions(propertyGroupFilterLogic(logicProps))

    // Update the logic's internal filters when the props change
    useEffect(() => {
        setFilters(propertyFilters ?? { groups: [] })
    }, [propertyFilters])

    return (
        <>
            {filtersWithNew.groups && (
                <div className="property-group-filters">
                    <BindLogic logic={propertyGroupFilterLogic} props={logicProps}>
                        <Row
                            align="middle"
                            justify="space-between"
                            className="pb pr mb"
                            style={{ borderBottom: '1px solid var(--border)' }}
                        >
                            <GlobalFiltersTitle orFiltering={true} />
                            {filtersWithNew.type && (
                                <AndOrFilterSelect
                                    value={filtersWithNew.type}
                                    onChange={(value) => setPropertyGroupsType(value)}
                                    topLevelFilter={true}
                                />
                            )}
                        </Row>
                        {filtersWithNew.groups.map((group: AndOrPropertyGroup, propertyGroupIndex: number) => {
                            return (
                                <>
                                    <div className="mt mb" style={style} key={propertyGroupIndex}>
                                        <Row justify="space-between" align="middle" className="mb-05">
                                            <AndOrFilterSelect
                                                onChange={(type) => setPropertyGroupType(type, propertyGroupIndex)}
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
                                            <DeleteOutlined
                                                onClick={() => removeFilterGroup(propertyGroupIndex)}
                                                style={{ fontSize: 16, color: 'var(--primary-alt)' }}
                                            />
                                        </Row>
                                        <PropertyFilters
                                            orFiltering={true}
                                            propertyFilters={group.groups}
                                            onChange={(properties) => {
                                                setPropertyFilters(properties, propertyGroupIndex)
                                            }}
                                            pageKey={`trends-filters-${propertyGroupIndex}`}
                                            taxonomicGroupTypes={taxonomicGroupTypes}
                                            eventNames={eventNames}
                                            propertyGroupType={group.type}
                                        />
                                    </div>
                                    {propertyGroupIndex !== filtersWithNew?.groups.length - 1 && (
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
                <Button
                    style={{
                        color: 'var(--primary)',
                        border: 'none',
                        boxShadow: 'none',
                    }}
                    className="mb"
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
    onChange: (type: AndOr) => void
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
                defaultValue={AndOr.AND}
                onChange={(type) => onChange(type)}
                dropdownMatchSelectWidth={false}
                placement={topLevelFilter ? 'bottomRight' : 'bottomLeft'}
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
