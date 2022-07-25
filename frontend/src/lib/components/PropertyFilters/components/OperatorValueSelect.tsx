import React, { useEffect, useState } from 'react'
import { PropertyDefinition, PropertyFilterValue, PropertyOperator, PropertyType } from '~/types'
import { Col, Select, SelectProps } from 'antd'
import {
    allOperatorsMapping,
    chooseOperatorMap,
    isMobile,
    isOperatorFlag,
    isOperatorMulti,
    isOperatorRange,
    isOperatorRegex,
} from 'lib/utils'
import { PropertyValue } from './PropertyValue'
import { ColProps } from 'antd/lib/col'
import { dayjs } from 'lib/dayjs'

export interface OperatorValueSelectProps {
    type?: string
    propkey?: string
    operator?: PropertyOperator | null
    value?: string | number | Array<string | number> | null
    columnOptions?: ColProps | [ColProps, ColProps]
    placeholder?: string
    endpoint?: string
    onChange: (operator: PropertyOperator, value: PropertyFilterValue) => void
    operatorSelectProps?: Omit<SelectProps<any>, 'onChange'>
    propertyDefinitions: PropertyDefinition[]
    defaultOpen?: boolean
}

interface OperatorSelectProps extends SelectProps<any> {
    operator: PropertyOperator
    operators: Array<PropertyOperator>
    onChange: (operator: PropertyOperator) => void
    defaultOpen?: boolean
}

function getValidationError(operator: PropertyOperator, value: any, property?: string): string | null {
    if (isOperatorRegex(operator)) {
        try {
            new RegExp(value)
        } catch (e: any) {
            return e.message
        }
    }
    if (isOperatorRange(operator) && isNaN(value)) {
        let message = `Range operators only work with numeric values`
        if (dayjs(value).isValid()) {
            const propertyReference = property ? `property ${property}` : 'this property'
            message += `. If you'd like to compare dates and times, make sure ${propertyReference} is typed as DateTime in Data Management. You will then be able to use operators "before" and "after"`
        }
        return message
    }
    return null
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
    propertyDefinitions = [],
    defaultOpen,
}: OperatorValueSelectProps): JSX.Element {
    const propertyDefinition = propertyDefinitions.find((pd) => pd.name === propkey)

    // DateTime properties should not default to Exact
    const startingOperator =
        propertyDefinition?.property_type == PropertyType.DateTime && (!operator || operator == PropertyOperator.Exact)
            ? PropertyOperator.IsDateExact
            : operator || PropertyOperator.Exact
    const [currentOperator, setCurrentOperator] = useState(startingOperator)
    const [validationError, setValidationError] = useState<string | null>(null)

    const [operators, setOperators] = useState([] as Array<PropertyOperator>)
    useEffect(() => {
        const operatorMapping: Record<string, string> = chooseOperatorMap(propertyDefinition?.property_type)
        setOperators(Object.keys(operatorMapping) as Array<PropertyOperator>)
    }, [propertyDefinition])

    return (
        <>
            <Col {...(Array.isArray(columnOptions) ? columnOptions[0] : columnOptions)}>
                <OperatorSelect
                    operator={currentOperator || PropertyOperator.Exact}
                    operators={operators}
                    onChange={(newOperator: PropertyOperator) => {
                        const tentativeValidationError =
                            newOperator && value ? getValidationError(newOperator, value, propkey) : null
                        if (tentativeValidationError) {
                            setValidationError(tentativeValidationError)
                            return
                        } else {
                            setValidationError(null)
                        }
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
                    defaultOpen={defaultOpen}
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
                            const tentativeValidationError =
                                currentOperator && newValue
                                    ? getValidationError(currentOperator, newValue, propkey)
                                    : null
                            if (tentativeValidationError) {
                                setValidationError(tentativeValidationError)
                                return
                            } else {
                                setValidationError(null)
                            }
                            onChange(currentOperator || PropertyOperator.Exact, newValue)
                        }}
                        // open automatically only if new filter
                        autoFocus={!isMobile() && value === null}
                    />
                </Col>
            )}
            {validationError && <span className="taxonomic-validation-error">{validationError}</span>}
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
