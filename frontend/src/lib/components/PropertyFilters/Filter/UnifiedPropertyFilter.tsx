/*
Contains the **new** property filter (see #4050) component where all filters are unified in a single view
*/
import React, { useState } from 'react'
import { Button, Col, Row } from 'antd'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
// import { cohortsModel } from '../../../../models/cohortsModel'
import { useValues, useActions } from 'kea'
import { SelectGradientOverflowProps } from 'lib/components/SelectGradientOverflow'
import { Link } from '../../Link'
import { DownOutlined } from '@ant-design/icons'
import { OperatorValueFilterType, OperatorValueSelect } from 'lib/components/PropertyFilters/OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { propertyFilterLogic } from '../propertyFilterLogic'
import { PropertyOptionGroup } from '../PropertySelect'
import { SelectBox, SelectBoxItem } from 'lib/components/SelectBox'

function FilterDropdown({ open, children }: { open: boolean; children: React.ReactNode }): JSX.Element | null {
    return open ? <div>{children}</div> : null
}
interface PropertyFilterProps {
    index: number
    onComplete: CallableFunction
    logic: typeof propertyFilterLogic
    selectProps: Partial<SelectGradientOverflowProps>
}

export function UnifiedPropertyFilter({ index, onComplete, logic }: PropertyFilterProps): JSX.Element {
    const { eventProperties, personProperties, filters } = useValues(logic)
    // const { cohorts } = useValues(cohortsModel)
    const { setFilter } = useActions(logic)
    const { key, value, operator, type } = filters[index]
    const [open, setOpen] = useState(false)

    const displayOperatorAndValue = key && type !== 'cohort'

    const setThisFilter = (
        newKey: string,
        newValue: OperatorValueFilterType | undefined,
        newOperator: string | undefined,
        newType: string
    ): void => {
        setFilter(index, newKey, newValue, newOperator, newType)
    }

    const optionGroups = [
        {
            type: 'event',
            label: 'Event properties',
            options: eventProperties,
        },
        {
            type: 'person',
            label: 'User properties',
            options: personProperties,
        },
    ] as PropertyOptionGroup[]

    if (eventProperties.length > 0) {
        optionGroups.push({
            type: 'element',
            label: 'Elements',
            options: ['tag_name', 'text', 'href', 'selector'].map((option) => ({
                value: option,
                label: option,
            })),
        })
    }

    type PropertiesType = {
        value: string
        label: string
        is_numerical: boolean
    }

    const selectBoxItems: SelectBoxItem[] = [
        {
            name: 'Event properties',
            header: function eventPropertiesHeader(label: string) {
                return <>{label}</>
            },
            dataSource: eventProperties?.map(({ value, label, is_numerical }: PropertiesType) => ({
                name: label,
                key: value,
                value,
                is_numerical,
            })),
            renderInfo: function eventPropertiesRenderInfo({ item }) {
                return (
                    <>
                        Event properties
                        <br />
                        <h3>{item.name}</h3>
                        {(item?.volume_30_day ?? 0 > 0) && (
                            <>
                                Seen <strong>{item.volume_30_day}</strong> times.{' '}
                            </>
                        )}
                        {(item?.query_usage_30_day ?? 0 > 0) && (
                            <>
                                Used in <strong>{item.query_usage_30_day}</strong> queries.
                            </>
                        )}
                    </>
                )
            },
            type: 'event',
            getValue: (item) => item.name || '',
            getLabel: (item) => item.name || '',
        },
        {
            name: 'User properties',
            header: function personPropertiesHeader(label: string) {
                return <>{label}</>
            },
            dataSource: personProperties?.map(({ value, label, is_numerical }: PropertiesType) => ({
                name: label,
                key: value,
                value,
                is_numerical,
            })),
            renderInfo: function personPropertiesRenderInfo({ item }) {
                return (
                    <>
                        User properties
                        <br />
                        <h3>{item.name}</h3>
                        {(item?.volume_30_day ?? 0 > 0) && (
                            <>
                                Seen <strong>{item.volume_30_day}</strong> times.{' '}
                            </>
                        )}
                        {(item?.query_usage_30_day ?? 0 > 0) && (
                            <>
                                Used in <strong>{item.query_usage_30_day}</strong> queries.
                            </>
                        )}
                    </>
                )
            },
            type: 'person',
            getValue: (item) => item.name || '',
            getLabel: (item) => item.name || '',
        },
    ]

    const onClick = (): void => {
        setOpen(!open)
    }

    return (
        <>
            <Row gutter={8} wrap={false}>
                <Col
                    style={{
                        height: '32px', // matches antd Select height
                        flexShrink: 0,
                        display: 'flex',
                        alignItems: 'center',
                    }}
                >
                    <span style={{ opacity: key ? 1 : 0.6 }}>
                        <span
                            style={{
                                color: '#C4C4C4',
                                fontSize: 18,
                                paddingLeft: 6,
                                paddingRight: 8,
                                position: 'relative',
                                top: -4,
                            }}
                        >
                            &#8627;
                        </span>
                        {index === 0 ? 'where' : 'and'}
                    </span>
                </Col>
                <Col style={{ minWidth: '6em' }}>
                    <Button onClick={onClick} style={{ display: 'flex', alignItems: 'center' }}>
                        <span className="text-overflow" style={{ maxWidth: '100%' }}>
                            <PropertyKeyInfo value={key || 'Select property'} />
                        </span>
                        <DownOutlined style={{ fontSize: 10 }} />
                    </Button>
                    <FilterDropdown open={open}>
                        <SelectBox
                            selectedItemKey={undefined}
                            onDismiss={() => setOpen(false)}
                            onSelect={(itemType, id, name) => {
                                setThisFilter(name, undefined, operator, itemType)
                                setOpen(false)
                            }}
                            items={selectBoxItems}
                        />
                    </FilterDropdown>
                </Col>

                {displayOperatorAndValue && (
                    <OperatorValueSelect
                        type={type}
                        propkey={key}
                        operator={operator}
                        value={value}
                        onChange={(newOperator, newValue) => {
                            setThisFilter(key, newValue, newOperator, type)
                            if (
                                newOperator &&
                                newValue &&
                                !(isOperatorMulti(newOperator) || isOperatorRegex(newOperator))
                            ) {
                                onComplete()
                            }
                        }}
                        columnOptions={[
                            {
                                style: {
                                    minWidth: '6em',
                                },
                            },
                            {
                                style: {
                                    flexShrink: 1,
                                    maxWidth: '50vw',
                                    minWidth: '11em',
                                },
                            },
                        ]}
                        operatorSelectProps={{
                            dropdownMatchSelectWidth: 200,
                            style: { maxWidth: '100%' },
                        }}
                    />
                )}
            </Row>
            {/* <SelectGradientOverflow
                style={{ width: '100%' }}
                showSearch
                optionFilterProp="children"
                labelInValue
                placeholder="Cohort name"
                value={
                    displayOperatorAndValue
                        ? { value: '' }
                        : {
                              value: value,
                              label: cohorts?.find((cohort) => cohort.id === value)?.name || value,
                          }
                }
                onChange={(_, newFilter) => {
                    onComplete()
                    const { value: newValue, type: newType } = newFilter as { value: string; type: string }
                    setThisFilter('id', newValue, undefined, newType)
                }}
                data-attr="cohort-filter-select"
                {...selectProps}
            >
                {cohorts.map((item, idx) => (
                    <Select.Option
                        className="ph-no-capture"
                        key={'cohort-filter-' + idx}
                        value={item.id}
                        type="cohort"
                        data-attr={'cohort-filter-' + idx}
                    >
                        {item.name}
                    </Select.Option>
                ))}
            </SelectGradientOverflow> */}
            {type === 'cohort' && value ? (
                <Link to={`/cohorts/${value}`} target="_blank">
                    <Col style={{ marginLeft: 10, marginTop: 5 }}> View </Col>
                </Link>
            ) : null}
        </>
    )
}
