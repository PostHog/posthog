import React, { useState } from 'react'
import { PropertyOperator } from '~/types'
import { Col, Select } from 'antd'
import { isOperatorFlag, operatorMap } from 'lib/utils'
import { PropertyValue } from 'lib/components/PropertyFilters/PropertyValue'

interface OperatorValueSelectProps {
    type: string
    propkey: string
    operator: PropertyOperator | undefined
    value: string | number | null
    onChange: (operator: PropertyOperator, value: string | number | null) => void
}

interface OperatorSelectProps {
    operator: PropertyOperator
    operators: Array<PropertyOperator>
    onChange: (operator: PropertyOperator) => void
}

export function OperatorValueSelect({
    type,
    propkey,
    operator,
    value,
    onChange,
}: OperatorValueSelectProps): JSX.Element {
    const [currentOperator, setCurrentOperator] = useState(operator)

    return (
        <>
            <Col flex={1}>
                <OperatorSelect
                    operator={operator || 'exact'}
                    operators={Object.keys(operatorMap) as Array<PropertyOperator>}
                    onChange={(newOperator: PropertyOperator) => {
                        setCurrentOperator(newOperator)
                        if (isOperatorFlag(newOperator)) {
                            onChange(newOperator, newOperator)
                        } else if (isOperatorFlag(currentOperator || 'exact')) {
                            onChange(newOperator, null)
                        } else {
                            onChange(newOperator, value)
                        }
                    }}
                />
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
                            onChange(currentOperator || 'exact', value)
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

export function OperatorSelect({ operator, operators, onChange }: OperatorSelectProps): JSX.Element {
    return (
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
                onChange(newOperator.value as PropertyOperator)
            }}
        >
            {operators.map((operator) => (
                <Select.Option key={operator} value={operator || 'exact'}>
                    {operatorMap[operator || 'exact']}
                </Select.Option>
            ))}
        </Select>
    )
}
