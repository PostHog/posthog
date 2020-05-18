import React from 'react'
import Select from 'react-select'
import { selectStyle, operatorMap } from 'lib/utils'
import { PropertyValue } from './PropertyValue'
import { useValues, useActions } from 'kea'

const operatorOptions = Object.entries(operatorMap).map(([key, value]) => ({
    label: value,
    value: key,
}))

export function PropertyFilter({ index, endpoint, onComplete, logic }) {
    const { properties, filters } = useValues(logic)
    const { setFilter } = useActions(logic)
    let { key, value, operator, type } = filters[index]
    return (
        <div className="row" style={{ margin: '0.5rem -15px', minWidth: key ? 700 : 200 }}>
            {properties && (
                <div className={key ? 'col-4' : 'col'}>
                    <Select
                        options={properties}
                        value={[{ label: key, value: key }]}
                        isLoading={!properties}
                        placeholder="Property key"
                        onChange={item => setFilter(index, item.value, value, operator, type)}
                        styles={selectStyle}
                        autoFocus={!key}
                        openMenuOnFocus={true}
                    />
                </div>
            )}

            {key && (
                <div className="col-3 pl-0">
                    <Select
                        options={operatorOptions}
                        style={{ width: 200 }}
                        value={[
                            {
                                label: operatorMap[operator] || '= equals',
                                value: operator,
                            },
                        ]}
                        placeholder="Property key"
                        onChange={operator => setFilter(index, key, value, operator.value, type)}
                        styles={selectStyle}
                    />
                </div>
            )}
            {key && (
                <div className="col-5 pl-0" data-attr="prop-val">
                    <PropertyValue
                        endpoint={endpoint}
                        key={key}
                        propertyKey={key}
                        value={value}
                        onSet={(key, value) => {
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
