import React, { useState } from 'react'
import { PropertyOperator } from '~/types'
import { Col, Select } from 'antd'
import { isOperatorFlag, operatorMap } from 'lib/utils'
import { PropertyValue } from 'lib/components/PropertyFilters/PropertyValue'

interface Props {
    type: string
    propkey: string
    operator: PropertyOperator
    value: string | number | null
    onChange: (operator: PropertyOperator, value: string | number | null) => void
}

export function OperatorValueSelect({ type, propkey, operator, value, onChange }: Props): JSX.Element {
    const [currentOperator, setCurrentOperator] = useState(operator)

    return (
        <>
            <Col flex={1}>
                <Select
                    style={{ width: '100%' }}
                    defaultActiveFirstOption
                    labelInValue
                    value={{
                        value: currentOperator || '=',
                        label: operatorMap[currentOperator || 'exact'],
                    }}
                    placeholder="Property key"
                    onChange={(_, newOperator) => {
                        setCurrentOperator(newOperator.value)
                        if (isOperatorFlag(newOperator.value)) {
                            onChange(newOperator.value, newOperator.value)
                        } else if (isOperatorFlag(currentOperator || 'exact')) {
                            onChange(newOperator.value, null)
                        } else if (value) {
                            onChange(newOperator.value, value)
                        }
                    }}
                >
                    {Object.keys(operatorMap).map((operator) => (
                        <Select.Option key={operator} value={operator}>
                            {operatorMap[operator || 'exact']}
                        </Select.Option>
                    ))}
                </Select>
            </Col>
            {!isOperatorFlag(currentOperator || 'exact') && (
                <Col flex={1}>
                    <PropertyValue
                        type={type}
                        key={propkey}
                        propertyKey={propkey}
                        operator={operator}
                        value={value}
                        onSet={(value: string | number | null) => {
                            onChange(currentOperator, value)
                        }}
                    />
                    {(operator === 'gt' || operator === 'lt') && isNaN(value) && (
                        <p className="text-danger">Value needs to be a number. Try "equals" or "contains" instead.</p>
                    )}
                </Col>
            )}
        </>
    )
}
