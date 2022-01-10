import React, { useState } from 'react'
import { PropertyFilterValue, PropertyOperator } from '~/types'
import { Col, Select, SelectProps } from 'antd'
import {
    dateTimeOperatorMap,
    isMobile,
    isOperatorFlag,
    isOperatorMulti,
    allOperatorsMapping,
    genericOperatorMap,
} from 'lib/utils'
import { PropertyValue } from './PropertyValue'
import { ColProps } from 'antd/lib/col'
import { useValues } from 'kea'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

interface OperatorValueSelectProps {
    type?: string
    propkey?: string
    operator?: PropertyOperator | null
    value?: string | number | Array<string | number> | null
    columnOptions?: ColProps | [ColProps, ColProps]
    placeholder?: string
    endpoint?: string
    onChange: (operator: PropertyOperator, value: PropertyFilterValue) => void
    operatorSelectProps?: Omit<SelectProps<any>, 'onChange'>
    allowQueryingEventsByDateTime?: string | boolean
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
    placeholder,
    endpoint,
    onChange,
    operatorSelectProps,
    allowQueryingEventsByDateTime,
}: OperatorValueSelectProps): JSX.Element {
    const [currentOperator, setCurrentOperator] = useState(operator)
    const { propertyDefinitions } = useValues(propertyDefinitionsModel)

    const propertyDefinition = propertyDefinitions.find((pd) => pd.name === propkey)

    const operatorMapping =
        allowQueryingEventsByDateTime && propertyDefinition?.property_type == 'DateTime'
            ? dateTimeOperatorMap
            : genericOperatorMap
    const operators = Object.keys(operatorMapping) as Array<PropertyOperator>

    return (
        <>
            <Col {...(Array.isArray(columnOptions) ? columnOptions[0] : columnOptions)}>
                <OperatorSelect
                    operator={currentOperator || PropertyOperator.Exact}
                    operators={operators}
                    onChange={(newOperator: PropertyOperator) => {
                        setCurrentOperator(newOperator)
                        if (isOperatorFlag(newOperator)) {
                            onChange(newOperator, newOperator)
                        } else if (isOperatorFlag(currentOperator || PropertyOperator.Exact)) {
                            onChange(newOperator, null)
                        } else if (
                            isOperatorMulti(currentOperator || PropertyOperator.Exact) &&
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
            {!isOperatorFlag(currentOperator || PropertyOperator.Exact) && type && propkey && (
                <Col {...(Array.isArray(columnOptions) ? columnOptions[1] : columnOptions)}>
                    <PropertyValue
                        type={type}
                        key={propkey}
                        propertyKey={propkey}
                        endpoint={endpoint}
                        operator={currentOperator || PropertyOperator.Exact}
                        placeholder={placeholder}
                        value={value}
                        onSet={(newValue: string | number | string[] | null) => {
                            onChange(currentOperator || PropertyOperator.Exact, newValue)
                        }}
                        // open automatically only if new filter
                        autoFocus={!isMobile() && value === null}
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
                label: allOperatorsMapping[operator || PropertyOperator.Exact],
            }}
            placeholder="Property key"
            onChange={(_value, op) => {
                const newOperator = op as typeof op & CustomOptionsType
                onChange(newOperator.value)
            }}
            {...props}
        >
            {operators.map((op) => (
                <Select.Option key={op} value={op || PropertyOperator.Exact} className={'operator-value-option'}>
                    {allOperatorsMapping[op || PropertyOperator.Exact]}
                </Select.Option>
            ))}
        </Select>
    )
}
