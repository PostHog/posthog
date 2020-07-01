import React from 'react'
import { Select, Tabs } from 'antd'
import { operatorMap, isOperatorFlag } from 'lib/utils'
import { PropertyValue } from './PropertyValue'
import { PropertyKeyInfo, keyMapping } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '../../../models/cohortsModel'
import { useValues, useActions } from 'kea'

const { TabPane } = Tabs

export function PropertyFilter({ index, onComplete, logic }) {
    const { eventProperties, personProperties, filters } = useValues(logic)
    const { cohorts } = useValues(cohortsModel)
    const { setFilter } = useActions(logic)
    let { key, value, operator, type } = filters[index]

    const displayOperatorAndValue = key && type !== 'cohort'

    return (
        <Tabs
            defaultActiveKey={type === 'cohort' ? 'cohort' : 'property'}
            tabPosition="top"
            style={{ minWidth: displayOperatorAndValue ? 700 : 350 }}
        >
            <TabPane tab="Property" key="property" style={{ display: 'flex' }}>
                <div className={displayOperatorAndValue ? 'col-4 pl-0' : 'col p-0'}>
                    <Select
                        showSearch
                        autoFocus={!key}
                        defaultOpen={!key}
                        placeholder="Property key"
                        labelInValue
                        value={
                            type === 'cohort'
                                ? { key: '' }
                                : {
                                      key,
                                      label: keyMapping[type === 'element' ? 'element' : 'event'][key]?.label || key,
                                  }
                        }
                        filterOption={(input, option) => option.value?.toLowerCase().indexOf(input.toLowerCase()) >= 0}
                        onChange={(_, new_key) =>
                            setFilter(
                                index,
                                new_key.value.replace(/event_|person_|element_/gi, ''),
                                undefined,
                                operator,
                                new_key.type
                            )
                        }
                        style={{ width: '100%' }}
                        virtual={false}
                    >
                        {eventProperties.length > 0 && (
                            <Select.OptGroup key="event properties" label="Event properties">
                                {eventProperties.map((item, index) => (
                                    <Select.Option
                                        key={'event_' + item.value}
                                        value={'event_' + item.value}
                                        type="event"
                                        data-attr={'prop-filter-event-' + index}
                                    >
                                        <PropertyKeyInfo value={item.value} />
                                    </Select.Option>
                                ))}
                            </Select.OptGroup>
                        )}
                        {personProperties && (
                            <Select.OptGroup key="user properties" label="User properties">
                                {personProperties.map((item, index) => (
                                    <Select.Option
                                        key={'person_' + item.value}
                                        value={'person_' + item.value}
                                        type="person"
                                        data-attr={'prop-filter-person-' + index}
                                    >
                                        <PropertyKeyInfo value={item.value} />
                                    </Select.Option>
                                ))}
                            </Select.OptGroup>
                        )}
                        {eventProperties.length > 0 && (
                            <Select.OptGroup key="elements" label="Elements">
                                {['tag_name', 'text', 'href', 'selector'].map((item, index) => (
                                    <Select.Option
                                        key={'element_' + item}
                                        value={'element_' + item}
                                        type="element"
                                        data-attr={'prop-filter-element-' + index}
                                    >
                                        <PropertyKeyInfo value={item} type="element" />
                                    </Select.Option>
                                ))}
                            </Select.OptGroup>
                        )}
                    </Select>
                </div>
                {displayOperatorAndValue && (
                    <div className={isOperatorFlag(operator) ? 'col-8 p-0' : 'col-3 pl-0'}>
                        <Select
                            style={{ width: '100%' }}
                            defaultActiveFirstOption
                            labelInValue
                            value={{
                                value: operator || '=',
                                label: operatorMap[operator || 'exact'],
                            }}
                            placeholder="Property key"
                            onChange={(_, new_operator) => {
                                let new_value = value
                                if (isOperatorFlag(new_operator.value)) {
                                    // change value to induce reload
                                    new_value = new_operator.value
                                    onComplete()
                                } else {
                                    // clear value if switching from nonparametric (flag) to parametric
                                    if (isOperatorFlag(operator)) new_value = undefined
                                }
                                setFilter(index, key, new_value, new_operator.value, type)
                            }}
                        >
                            {Object.keys(operatorMap).map(operator => (
                                <Select.Option key={operator} value={operator}>
                                    {operatorMap[operator || 'exact']}
                                </Select.Option>
                            ))}
                        </Select>
                    </div>
                )}
                {displayOperatorAndValue && !isOperatorFlag(operator) && (
                    <div className="col-5 p-0">
                        <PropertyValue
                            type={type}
                            key={key}
                            propertyKey={key}
                            operator={operator}
                            value={value}
                            onSet={value => {
                                onComplete()
                                setFilter(index, key, value, operator, type)
                            }}
                        />
                        {(operator === 'gt' || operator === 'lt') && isNaN(value) && (
                            <p className="text-danger">
                                Value needs to be a number. Try "equals" or "contains" instead.
                            </p>
                        )}
                    </div>
                )}
            </TabPane>
            <TabPane tab="Cohort" key="cohort">
                <Select
                    style={{ width: '100%' }}
                    labelInValue
                    placeholder="Cohort name"
                    value={
                        type !== 'cohort'
                            ? { key: '' }
                            : {
                                  key,
                                  label: cohorts?.find(cohort => cohort.id === parseInt(key.substring(1)))?.name || key,
                              }
                    }
                    onChange={(_, new_cohort) => {
                        onComplete()
                        setFilter(index, `#${new_cohort.value}`, true, undefined, 'cohort')
                    }}
                >
                    {cohorts.map((item, index) => (
                        <Select.Option
                            key={'cohort_' + item.id}
                            value={item.id}
                            type="cohort"
                            data-attr={'prop-filter-event-' + index}
                        >
                            {item.name}
                        </Select.Option>
                    ))}
                </Select>
            </TabPane>
        </Tabs>
    )
}
