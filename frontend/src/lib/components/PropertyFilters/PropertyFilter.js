import React, { useCallback, useState } from 'react'
import { Col, Row, Select, Tabs } from 'antd'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '../../../models/cohortsModel'
import { useValues, useActions } from 'kea'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { Link } from '../Link'
import { PropertySelect } from './PropertySelect'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/OperatorValueSelect'

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
                        autoOpenIfEmpty
                        placeholder="Property key"
                    />
                </Col>

                {displayOperatorAndValue && (
                    <OperatorValueSelect
                        type={type}
                        propkey={propkey}
                        operator={operator}
                        value={value}
                        onChange={(newOperator, newValue) => {
                            setThisFilter(propkey, newValue, newOperator, type)
                            if (newOperator && newValue) {
                                onComplete()
                            }
                        }}
                        columnOptions={{ flex: 1 }}
                    />
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
