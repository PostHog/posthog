import { useEffect, useState } from 'react'
import { PropertyDefinition, PropertyFilterValue, PropertyOperator, PropertyType } from '~/types'
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
import { dayjs } from 'lib/dayjs'
import { LemonSelect, LemonSelectProps } from '@posthog/lemon-ui'

export interface OperatorValueSelectProps {
    type?: string
    propkey?: string
    operator?: PropertyOperator | null
    value?: string | number | Array<string | number> | null
    placeholder?: string
    endpoint?: string
    onChange: (operator: PropertyOperator, value: PropertyFilterValue) => void
    operatorSelectProps?: Omit<LemonSelectProps<any>, 'onChange'>
    eventNames?: string[]
    propertyDefinitions: PropertyDefinition[]
    defaultOpen?: boolean
}

interface OperatorSelectProps extends Omit<LemonSelectProps<any>, 'options'> {
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
    placeholder,
    endpoint,
    onChange,
    operatorSelectProps,
    propertyDefinitions = [],
    eventNames = [],
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
        const limitedElementProperty = propkey === 'selector' || propkey === 'tag_name'
        const operatorMapping: Record<string, string> = chooseOperatorMap(
            limitedElementProperty ? PropertyType.Selector : propertyDefinition?.property_type
        )
        const operators = Object.keys(operatorMapping) as Array<PropertyOperator>
        setOperators(operators)
        if (currentOperator !== operator) {
            setCurrentOperator(startingOperator)
        } else if (limitedElementProperty && !operators.includes(currentOperator)) {
            setCurrentOperator(PropertyOperator.Exact)
        }
    }, [propertyDefinition, propkey, operator])

    return (
        <>
            <div data-attr="taxonomic-operator">
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
            </div>
            {!isOperatorFlag(currentOperator || PropertyOperator.Exact) && type && propkey && (
                <div className="flex-1" style={{ minWidth: '10rem' }} data-attr="taxonomic-value-select">
                    <PropertyValue
                        type={type}
                        key={propkey}
                        propertyKey={propkey}
                        endpoint={endpoint}
                        operator={currentOperator || PropertyOperator.Exact}
                        placeholder={placeholder}
                        value={value}
                        eventNames={eventNames}
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
                </div>
            )}
            {validationError && <span className="taxonomic-validation-error">{validationError}</span>}
        </>
    )
}

export function OperatorSelect({ operator, operators, onChange, ...props }: OperatorSelectProps): JSX.Element {
    const operatorOptions = operators.map((op) => ({
        label: <span className="operator-value-option">{allOperatorsMapping[op || PropertyOperator.Exact]}</span>,
        value: op || PropertyOperator.Exact,
    }))
    return (
        <LemonSelect
            options={operatorOptions}
            value={operator || '='}
            placeholder="Property key"
            dropdownMatchSelectWidth={false}
            fullWidth
            onChange={(op) => {
                op && onChange(op)
            }}
            className={props.className}
        />
    )
}
