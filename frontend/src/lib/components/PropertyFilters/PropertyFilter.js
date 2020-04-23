import React, { Component } from 'react'
import Select from 'react-select'
import { selectStyle } from '../../utils'
import { PropertyValue } from './PropertyValue'
import { useValues, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'

export const operatorMap = {
    null: 'equals',
    is_not: "doesn't equal",
    icontains: 'contains',
    not_icontains: "doesn't contain",
    gt: 'greater than',
    lt: 'lower than',
}
const operatorOptions = Object.entries(operatorMap).map(([key, value]) => ({
    label: value,
    value: key,
}))

export function PropertyFilter({ index, endpoint, onChange, pageKey, onComplete }) {
    const { properties, filters } = useValues(propertyFilterLogic({ onChange, pageKey }))
    const { setFilter, remove } = useActions(propertyFilterLogic({ onChange, pageKey }))
    let item = filters[index]
    let key = Object.keys(item)[0] ? Object.keys(item)[0].split('__') : []
    let value = Object.values(item)[0]

    return (
        <div className="row" style={{ margin: '0.5rem -15px', minWidth: key[0] ? 700 : 200 }}>
            {properties && (
                <div className={key[0] ? 'col-4' : 'col'}>
                    <Select
                        options={properties}
                        value={[{ label: key[0], value: key[0] }]}
                        isLoading={!properties}
                        placeholder="Property key"
                        onChange={item =>
                            setFilter(
                                index,
                                item.value + (key[1] ? '__' + key[1] : ''),
                                item.value !== key[0] ? '' : value
                            )
                        }
                        styles={selectStyle}
                        autoFocus={!key[0]}
                        openMenuOnFocus={true}
                    />
                </div>
            )}

            {key[0] && (
                <div className="col-3 pl-0">
                    <Select
                        options={operatorOptions}
                        style={{ width: 200 }}
                        value={[
                            {
                                label: operatorMap[key[1]] || 'equals',
                                value: key[1],
                            },
                        ]}
                        placeholder="Property key"
                        onChange={operator => setFilter(index, key[0] + '__' + operator.value, value)}
                        styles={selectStyle}
                    />
                </div>
            )}
            {key[0] && (
                <div className="col-5 pl-0">
                    <PropertyValue
                        endpoint={endpoint}
                        key={Object.keys(item)[0]}
                        propertyKey={Object.keys(item)[0]}
                        value={value}
                        onSet={(key, value) => {
                            onComplete()
                            setFilter(index, key, value)
                        }}
                    />
                    {(key[1] == 'gt' || key[1] == 'lt') && isNaN(value) && (
                        <p className="text-danger">Value needs to be a number. Try "equals" or "contains" instead.</p>
                    )}
                </div>
            )}
        </div>
    )
}
