import React from 'react'
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
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { LemonDivider } from '../LemonDivider'

interface PropertyGroupFilters {
    value: PropertyGroupFilter
    onChange: (filters: PropertyGroupFilter) => void
    pageKey: string
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    eventNames?: string[]
    setTestFilters: (filters: Partial<FilterType>) => void
    filters: Partial<FilterType>
    noTitle?: boolean
}

export function PropertyGroupFilters({
    value,
    onChange,
    pageKey,
    taxonomicGroupTypes,
    eventNames = [],
    setTestFilters,
    filters,
    noTitle,
}: PropertyGroupFilters): JSX.Element {
    const logicProps = { value, onChange, pageKey }
    const { propertyGroupFilter } = useValues(propertyGroupFilterLogic(logicProps))
    const {
        addFilterGroup,
        removeFilterGroup,
        setOuterPropertyGroupsType,
        setInnerPropertyGroupType,
        setPropertyFilters,
        duplicateFilterGroup,
    } = useActions(propertyGroupFilterLogic(logicProps))

    const showHeader = !noTitle || (propertyGroupFilter.type && propertyGroupFilter.values.length > 1)

    return (
        <>
            {propertyGroupFilter.values && (
                <div className="property-group-filters">
                    <BindLogic logic={propertyGroupFilterLogic} props={logicProps}>
                        {showHeader ? (
                            <div className="flex-center space-between-items">
                                {!noTitle ? <GlobalFiltersTitle orFiltering={true} /> : null}
                                {propertyGroupFilter.type && propertyGroupFilter.values.length > 1 && (
                                    <AndOrFilterSelect
                                        value={propertyGroupFilter.type}
                                        onChange={(value) => setOuterPropertyGroupsType(value)}
                                        topLevelFilter={true}
                                    />
                                )}
                            </div>
                        ) : null}
                        <LemonDivider large />
                        <TestAccountFilter filters={filters} onChange={(testFilters) => setTestFilters(testFilters)} />
                        <div className="mt">
                            {propertyGroupFilter.values?.map(
                                (group: PropertyGroupFilterValue, propertyGroupIndex: number) => {
                                    return (
                                        <React.Fragment key={propertyGroupIndex}>
                                            <div className="property-group">
                                                <Row justify="space-between" align="middle" className="mb-05">
                                                    <AndOrFilterSelect
                                                        onChange={(type) =>
                                                            setInnerPropertyGroupType(type, propertyGroupIndex)
                                                        }
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
                                                        type="alt"
                                                        onClick={() => duplicateFilterGroup(propertyGroupIndex)}
                                                        size="small"
                                                    />
                                                    <LemonButton
                                                        icon={<IconDelete />}
                                                        type="alt"
                                                        onClick={() => removeFilterGroup(propertyGroupIndex)}
                                                        size="small"
                                                    />
                                                </Row>
                                                <PropertyFilters
                                                    orFiltering={true}
                                                    propertyFilters={group.values}
                                                    style={{ marginBottom: 0 }}
                                                    onChange={(properties) => {
                                                        setPropertyFilters(properties, propertyGroupIndex)
                                                    }}
                                                    pageKey={`insight-filters-${propertyGroupIndex}`}
                                                    taxonomicGroupTypes={taxonomicGroupTypes}
                                                    eventNames={eventNames}
                                                    propertyGroupType={group.type}
                                                />
                                            </div>
                                            {propertyGroupIndex !== propertyGroupFilter.values.length - 1 && (
                                                <div className="property-group-and-or-separator">
                                                    <span>{propertyGroupFilter.type}</span>
                                                </div>
                                            )}
                                        </React.Fragment>
                                    )
                                }
                            )}
                        </div>
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
    prefix?: React.ReactNode
    suffix?: React.ReactNode
}

export function AndOrFilterSelect({
    onChange,
    value,
    topLevelFilter,
    prefix = 'Match',
    suffix = 'filters in this group',
}: AndOrFilterSelectProps): JSX.Element {
    return (
        <Row align="middle" wrap={false} className="and-or-filter">
            <span className="ml-05">{prefix}</span>
            <Select
                optionLabelProp="label"
                dropdownClassName="and-or-filter-select"
                style={{ marginLeft: 8, marginRight: 8 }}
                value={value}
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
            {suffix}
        </Row>
    )
}
