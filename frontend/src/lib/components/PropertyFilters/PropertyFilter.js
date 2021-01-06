import React, { useCallback, useState } from 'react'
import { Col, Row, Select, Tabs } from 'antd'
import { operatorMap, isOperatorFlag } from 'lib/utils'
import { PropertyValue } from './PropertyValue'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '../../../models/cohortsModel'
import { useValues, useActions } from 'kea'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { Link } from '../Link'
import { PropertySelect } from './PropertySelect'

const { TabPane } = Tabs

function PropertyPaneContents({
    onComplete,
    setThisFilter,
    eventProperties,
    personProperties,
    propkey,
    value,
    operator,
    type,
    displayOperatorAndValue,
}) {
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
    ]

    if (eventProperties.length > 0) {
        optionGroups.push({
            type: 'element',
            label: 'Elements',
            options: ['tag_name', 'text', 'href', 'selector'].map((value) => ({ value, label: value })),
        })
    }

    return (
        <>
            <Row gutter={8} className="full-width">
                <Col flex={1}>
                    <PropertySelect
                        value={
                            type === 'cohort'
                                ? null
                                : {
                                      value: propkey,
                                      label:
                                          keyMapping[type === 'element' ? 'element' : 'event'][propkey]?.label ||
                                          propkey,
                                  }
                        }
                        onChange={(type, value) =>
                            setThisFilter(
                                value,
                                undefined,
                                value === '$active_feature_flags' ? 'icontains' : operator,
                                type
                            )
                        }
                        optionGroups={optionGroups}
                    />
                </Col>
                {displayOperatorAndValue && (
                    <Col flex={1}>
                        <Select
                            style={{ width: '100%' }}
                            defaultActiveFirstOption
                            labelInValue
                            value={{
                                value: operator || '=',
                                label: operatorMap[operator || 'exact'],
                            }}
                            placeholder="Property key"
                            onChange={(_, newOperator) => {
                                let newValue = value
                                if (isOperatorFlag(newOperator.value)) {
                                    // change value to induce reload
                                    newValue = newOperator.value
                                    onComplete()
                                } else {
                                    // clear value if switching from nonparametric (flag) to parametric
                                    if (isOperatorFlag(operator)) {
                                        newValue = undefined
                                    }
                                }
                                setThisFilter(propkey, newValue, newOperator.value, type)
                            }}
                        >
                            {Object.keys(operatorMap).map((operator) => (
                                <Select.Option key={operator} value={operator}>
                                    {operatorMap[operator || 'exact']}
                                </Select.Option>
                            ))}
                        </Select>
                    </Col>
                )}
                {displayOperatorAndValue && !isOperatorFlag(operator) && (
                    <Col flex={1}>
                        <PropertyValue
                            type={type}
                            key={propkey}
                            propertyKey={propkey}
                            operator={operator}
                            value={value}
                            onSet={(value) => {
                                onComplete()
                                setThisFilter(propkey, value, operator, type)
                            }}
                        />
                        {(operator === 'gt' || operator === 'lt') && isNaN(value) && (
                            <p className="text-danger">
                                Value needs to be a number. Try "equals" or "contains" instead.
                            </p>
                        )}
                    </Col>
                )}
            </Row>
        </>
    )
}

function CohortPaneContents({ onComplete, setThisFilter, value, displayOperatorAndValue }) {
    const { cohorts } = useValues(cohortsModel)

    return (
        <>
            <SelectGradientOverflow
                className={rrwebBlockClass}
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
                    setThisFilter('id', newFilter.value, undefined, newFilter.type)
                }}
                data-attr="cohort-filter-select"
            >
                {cohorts.map((item, index) => (
                    <Select.Option
                        key={'cohort-filter-' + index}
                        value={item.id}
                        type="cohort"
                        data-attr={'cohort-filter-' + index}
                    >
                        {item.name}
                    </Select.Option>
                ))}
            </SelectGradientOverflow>
        </>
    )
}

export function PropertyFilter({ index, onComplete, logic }) {
    const { eventProperties, personProperties, filters } = useValues(logic)
    const { setFilter } = useActions(logic)
    let { key, value, operator, type } = filters[index]
    const [activeKey, setActiveKey] = useState(type === 'cohort' ? 'cohort' : 'property')

    const setThisFilter = useCallback((key, value, operator, type) => setFilter(index, key, value, operator, type), [
        index,
    ])

    const displayOperatorAndValue = key && type !== 'cohort'

    return (
        <Tabs
            defaultActiveKey={type === 'cohort' ? 'cohort' : 'property'}
            onChange={setActiveKey}
            tabPosition="top"
            animated={false}
            style={{ minWidth: displayOperatorAndValue ? 700 : 350 }}
        >
            <TabPane
                tab="Property"
                key="property"
                style={{ display: 'flex', marginLeft: activeKey === 'cohort' ? '-100%' : 0 }}
            >
                <PropertyPaneContents
                    onComplete={onComplete}
                    setThisFilter={setThisFilter}
                    eventProperties={eventProperties}
                    personProperties={personProperties}
                    propkey={key}
                    value={value}
                    operator={operator}
                    type={type}
                    displayOperatorAndValue={displayOperatorAndValue}
                />
            </TabPane>
            <TabPane tab="Cohort" key="cohort" style={{ display: 'flex' }}>
                <CohortPaneContents
                    onComplete={onComplete}
                    setThisFilter={setThisFilter}
                    value={value}
                    displayOperatorAndValue={displayOperatorAndValue}
                />
                {type === 'cohort' && value ? (
                    <Link to={`/cohorts/${value}`} target="_blank">
                        <Col style={{ marginLeft: 10, marginTop: 5 }}> View </Col>
                    </Link>
                ) : null}
            </TabPane>
        </Tabs>
    )
}
