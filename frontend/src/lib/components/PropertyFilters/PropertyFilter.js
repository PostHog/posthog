import React from 'react'
import { Select } from 'antd'
import { operatorMap } from 'lib/utils'
import { PropertyValue } from './PropertyValue'
import { useValues, useActions } from 'kea'

export function PropertyFilter({ index, endpoint, onComplete, logic }) {
    const { eventProperties, personProperties, filters } = useValues(logic)
    const { setFilter } = useActions(logic)
    let { key, value, operator, type } = filters[index]
    return (
        <div className="row" style={{ margin: '0.5rem -15px', minWidth: key ? 700 : 200 }}>
            <div className={key ? 'col-4' : 'col'}>
                <Select
                    showSearch
                    autoFocus={!key}
                    defaultOpen={!key}
                    placeholder="Property key"
                    value={key}
                    filterOption={(input, option) => option.children?.toLowerCase().indexOf(input.toLowerCase()) >= 0}
                    onChange={(_, new_key) => setFilter(index, new_key.children, undefined, operator, new_key.type)}
                    style={{ width: '100%' }}
                >
                    {eventProperties.length > 0 && (
                        <Select.OptGroup key="Event properties" lable="Event properties">
                            {eventProperties.map(item => (
                                <Select.Option key={'event_' + item.value} value={'event_' + item.value} type="event">
                                    {item.value}
                                </Select.Option>
                            ))}
                        </Select.OptGroup>
                    )}
                    {personProperties && (
                        <Select.OptGroup key="User properties" lable="User properties">
                            {personProperties.map(item => (
                                <Select.Option
                                    key={'person_' + item.value}
                                    value={'person_' + item.value}
                                    type="person"
                                >
                                    {item.value}
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
                        onChange={(_, operator) => setFilter(index, key, value, operator.value, type)}
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
                        endpoint={endpoint}
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
