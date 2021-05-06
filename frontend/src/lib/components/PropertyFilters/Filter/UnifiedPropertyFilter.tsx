import React from 'react'
import { Col, Row, Select } from 'antd'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '../../../../models/cohortsModel'
import { useValues, useActions } from 'kea'
import { SelectGradientOverflow, SelectGradientOverflowProps } from 'lib/components/SelectGradientOverflow'
import { Link } from '../../Link'
import { PropertySelect } from '../PropertySelect'
import { OperatorValueFilterType, OperatorValueSelect } from 'lib/components/PropertyFilters/OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { propertyFilterLogic } from '../propertyFilterLogic'
import { PropertyOptionGroup } from '../PropertySelect'

interface PropertyFilterProps {
    index: number
    onComplete: CallableFunction
    logic: typeof propertyFilterLogic
    selectProps: Partial<SelectGradientOverflowProps>
}

export function UnifiedPropertyFilter({ index, onComplete, logic, selectProps }: PropertyFilterProps): JSX.Element {
    const { eventProperties, personProperties, filters } = useValues(logic)
    const { cohorts } = useValues(cohortsModel)
    const { setFilter } = useActions(logic)
    const { key, value, operator, type } = filters[index]

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

    return (
        <>
            <Row gutter={8} className="full-width" wrap={false}>
                <Col
                    style={{
                        height: '32px', // matches antd Select height
                        flexShrink: 0,
                        display: 'flex',
                        alignItems: 'center',
                    }}
                >
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
                    where
                </Col>
                <Col style={{ minWidth: '6em' }}>
                    <PropertySelect
                        value={
                            type === 'cohort'
                                ? null
                                : {
                                      value: key,
                                      label: keyMapping[type === 'element' ? 'element' : 'event'][key]?.label || key,
                                  }
                        }
                        onChange={(newType, newValue) =>
                            setThisFilter(
                                newValue,
                                undefined,
                                newValue === '$active_feature_flags' ? 'icontains' : operator,
                                newType
                            )
                        }
                        optionGroups={optionGroups}
                        placeholder="Property key"
                        dropdownMatchSelectWidth={250}
                    />
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
            <SelectGradientOverflow
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
            </SelectGradientOverflow>
            {type === 'cohort' && value ? (
                <Link to={`/cohorts/${value}`} target="_blank">
                    <Col style={{ marginLeft: 10, marginTop: 5 }}> View </Col>
                </Link>
            ) : null}
        </>
    )
}
