import React, { useState } from 'react'
import { PropertyOperator } from '~/types'
import { Col, Select, SelectProps } from 'antd'
import { isOperatorFlag, isOperatorMulti, operatorMap } from 'lib/utils'
import { PropertyValue } from 'lib/components/PropertyFilters/PropertyValue'
import { ColProps } from 'antd/lib/col'

export type OperatorValueFilterType = string | number | Array<string | number> | null

interface OperatorValueSelectProps {
    type: string
    propkey: string
    operator: PropertyOperator | undefined
    value: string | number | Array<string | number> | null
    columnOptions?: ColProps | [ColProps, ColProps]
    onChange: (operator: PropertyOperator, value: OperatorValueFilterType) => void
    operatorSelectProps?: Omit<SelectProps<any>, 'onChange'>
}

interface OperatorSelectProps extends SelectProps<any> {
    operator: PropertyOperator
    operators: Array<PropertyOperator>
    onChange: (operator: PropertyOperator) => void
}

export function OperatorValueSelect({
    type,
    propkey,
    operator,
    value,
    columnOptions,
    onChange,
    operatorSelectProps,
}: OperatorValueSelectProps): JSX.Element {
    const [currentOperator, setCurrentOperator] = useState(operator)

    return (
        <>
            <Col {...(Array.isArray(columnOptions) ? columnOptions[0] : columnOptions)}>
                <OperatorSelect
                    operator={currentOperator || 'exact'}
                    operators={Object.keys(operatorMap) as Array<PropertyOperator>}
                    onChange={(newOperator: PropertyOperator) => {
                        setCurrentOperator(newOperator)
                        if (isOperatorFlag(newOperator)) {
                            onChange(newOperator, newOperator)
                        } else if (isOperatorFlag(currentOperator || 'exact')) {
                            onChange(newOperator, null)
                        } else if (
                            isOperatorMulti(currentOperator || 'exact') &&
                            !isOperatorMulti(newOperator) &&
                            Array.isArray(value)
                        ) {
                            onChange(newOperator, value[0])
                        } else if (value) {
                            onChange(newOperator, value)
                        }
                    }}
                    {...operatorSelectProps}
                />
            </Col>
            {!isOperatorFlag(currentOperator || 'exact') && (
                <Col {...(Array.isArray(columnOptions) ? columnOptions[1] : columnOptions)}>
                    <PropertyValue
                        type={type}
                        key={propkey}
                        propertyKey={propkey}
                        operator={currentOperator || 'exact'}
                        value={value}
                        onSet={(newValue: string | number | string[] | null) => {
                            onChange(currentOperator || 'exact', newValue)
                        }}
                    />
                </Col>
            )}
        </>
    )
}

type CustomOptionsType = {
    value: PropertyOperator
    label: string
}

export function OperatorSelect({ operator, operators, onChange, ...props }: OperatorSelectProps): JSX.Element {
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
            onChange={(_value, op) => {
                const newOperator = op as typeof op & CustomOptionsType
                onChange(newOperator.value)
            }}
            {...props}
        >
            {operators.map((op) => (
                <Select.Option key={op} value={op || 'exact'}>
                    {operatorMap[op || 'exact']}
                </Select.Option>
            ))}
        </Select>
    )
}
