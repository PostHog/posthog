import React from 'react'
import { Select } from 'antd'
import { operatorMap } from 'lib/utils'
import { PropertyValue } from './PropertyValue'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useValues, useActions } from 'kea'

export function PropertyFilter({ index, onComplete, logic }) {
    const { eventProperties, personProperties, filters } = useValues(logic)
    const { setFilter } = useActions(logic)
    let { key, value, operator, type } = filters[index]
    return (
        <div className="row" style={{ margin: '0.5rem -15px', minWidth: key ? 700 : 400 }}>
            <div className={key ? 'col-4' : 'col'}>
                <Select
                    showSearch
                    autoFocus={!key}
                    defaultOpen={!key}
                    placeholder="Property key"
                    value={key}
                    filterOption={(input, option) => option.value?.toLowerCase().indexOf(input.toLowerCase()) >= 0}
                    onChange={(_, new_key) => setFilter(index, new_key.value, undefined, operator, new_key.type)}
                    style={{ width: '100%' }}
                    virtual={false}
                >
                    {eventProperties.length > 0 && (
                        <Select.OptGroup key="Event properties" label="Event properties">
                            {eventProperties.map((item, index) => (
                                <Select.Option
                                    key={'event_' + item.value}
                                    value={item.value}
                                    type="event"
                                    data-attr={'prop-filter-event-' + index}
                                >
                                    <PropertyKeyInfo value={item.value} />
                                </Select.Option>
                            ))}
                        </Select.OptGroup>
                    )}
                    {personProperties && (
                        <Select.OptGroup key="User properties" label="User properties">
                            {personProperties.map((item, index) => (
                                <Select.Option
                                    key={'person_' + item.value}
                                    value={item.value}
                                    type="person"
                                    data-attr={'prop-filter-person-' + index}
                                >
                                    <PropertyKeyInfo value={item.value} />
                                </Select.Option>
                            ))}
                        </Select.OptGroup>
                    )}
                    {eventProperties.length > 0 && (
                        <Select.OptGroup key="Elements" label="Elements">
                            {['tag_name', 'text', 'href', 'selector'].map((item, index) => (
                                <Select.Option
                                    key={'element_' + item}
                                    value={item}
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

            {key && (
                <div className="col-3 pl-0">
                    <Select
                        style={{ width: '100%' }}
                        defaultActiveFirstOption
                        labelInValue
                        value={{
                            value: operator || '=',
                            label: operatorMap[operator] || '= equals',
                        }}
                        placeholder="Property key"
                        onChange={(_, new_operator) => {
                            let new_value = value
                            if (operator === 'is_set') new_value = undefined
                            if (new_operator.value === 'is_set') new_value = 'true'
                            setFilter(index, key, new_value, new_operator.value, type)
                        }}
                    >
                        {Object.keys(operatorMap).map(operator => (
                            <Select.Option key={operator} value={operator}>
                                {operatorMap[operator] || '= equals'}
                            </Select.Option>
                        ))}
                    </Select>
                </div>
            )}
            {key && (
                <div className="col-5 pl-0">
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
                        <p className="text-danger">Value needs to be a number. Try "equals" or "contains" instead.</p>
                    )}
                </div>
            )}
        </div>
    )
}
