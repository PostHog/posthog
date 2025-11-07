import { useEffect, useState } from 'react'

import { LemonDropdownProps, LemonSelect, LemonSelectProps } from '@posthog/lemon-ui'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { dayjs } from 'lib/dayjs'
import {
    allOperatorsMapping,
    chooseOperatorMap,
    isMobile,
    isOperatorCohort,
    isOperatorFlag,
    isOperatorMulti,
    isOperatorRange,
    isOperatorRegex,
} from 'lib/utils'

import {
    GroupTypeIndex,
    PropertyDefinition,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    PropertyType,
} from '~/types'

import { PropertyValue } from './PropertyValue'

export interface OperatorValueSelectProps {
    type?: PropertyFilterType
    propertyKey?: string
    operator?: PropertyOperator | null
    value?: PropertyFilterValue
    editable: boolean
    placeholder?: string
    endpoint?: string
    onChange: (operator: PropertyOperator, value: PropertyFilterValue) => void
    operatorSelectProps?: Partial<Omit<LemonSelectProps<any>, 'onChange'>>
    eventNames?: string[]
    propertyDefinitions: PropertyDefinition[]
    addRelativeDateTimeOptions?: boolean
    groupTypeIndex?: GroupTypeIndex
    size?: 'xsmall' | 'small' | 'medium'
    startVisible?: LemonDropdownProps['startVisible']
    /**
     * in some contexts you want to externally limit the available operators
     * this won't add an operator if it isn't valid
     * i.e. it limits the options shown from the options that would have been shown
     * **/
    operatorAllowlist?: Array<PropertyOperator>
}

interface OperatorSelectProps extends Omit<LemonSelectProps<any>, 'options'> {
    operator: PropertyOperator
    operators: Array<PropertyOperator>
    onChange: (operator: PropertyOperator) => void
    startVisible?: LemonDropdownProps['startVisible']
}

function getRegexValidationError(operator: PropertyOperator, value: any): string | null {
    if (isOperatorRegex(operator)) {
        try {
            new RegExp(value)
        } catch (e: any) {
            return e.message
        }
    }
    return null
}

function getValidationError(operator: PropertyOperator, value: any, property?: string): string | null {
    const regexErrorMessage = getRegexValidationError(operator, value)
    if (regexErrorMessage != null) {
        return regexErrorMessage
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
    propertyKey,
    operator,
    value,
    placeholder,
    endpoint,
    onChange,
    operatorSelectProps,
    propertyDefinitions = [],
    eventNames = [],
    addRelativeDateTimeOptions,
    groupTypeIndex = undefined,
    size,
    editable,
    startVisible,
    operatorAllowlist,
}: OperatorValueSelectProps): JSX.Element {
    const lookupKey = type === PropertyFilterType.DataWarehousePersonProperty ? 'id' : 'name'
    const propertyDefinition = propertyDefinitions.find((pd) => pd[lookupKey] === propertyKey)

    const isCohortProperty = propertyKey === 'id' && type === PropertyFilterType.Cohort

    // DateTime properties should not default to Exact
    const isDateTimeProperty = propertyDefinition?.property_type == PropertyType.DateTime

    const isInitialOperator = !operator || operator == PropertyOperator.Exact

    let startingOperator = operator || PropertyOperator.Exact
    if (isInitialOperator) {
        if (isDateTimeProperty) {
            startingOperator = PropertyOperator.IsDateExact
        } else if (isCohortProperty) {
            startingOperator = PropertyOperator.In
        }
    }

    const [currentOperator, setCurrentOperator] = useState(startingOperator)
    const [validationError, setValidationError] = useState<string | null>(null)

    const [operators, setOperators] = useState([] as Array<PropertyOperator>)
    useEffect(() => {
        let propertyType = propertyDefinition?.property_type
        if (propertyKey === 'selector' || propertyKey === 'tag_name') {
            propertyType = PropertyType.Selector
        } else if (propertyKey === 'id' && type === PropertyFilterType.Cohort) {
            propertyType = PropertyType.Cohort
        } else if (type === PropertyFilterType.Flag) {
            propertyType = PropertyType.Flag
        } else if (propertyKey === 'assignee' && type === PropertyFilterType.ErrorTrackingIssue) {
            propertyType = PropertyType.Assignee
        } else if (propertyKey === 'first_seen' && type === PropertyFilterType.ErrorTrackingIssue) {
            propertyType = PropertyType.DateTime
        } else if (
            type === PropertyFilterType.Event &&
            propertyKey &&
            ['$exception_types', '$exception_values', '$exception_sources', '$exception_functions'].includes(
                propertyKey
            )
        ) {
            propertyType = PropertyType.StringArray
        }

        const operatorMapping: Record<string, string> = chooseOperatorMap(propertyType)

        const operators = (Object.keys(operatorMapping) as Array<PropertyOperator>).filter((op) => {
            return !operatorAllowlist || operatorAllowlist.includes(op)
        })

        setOperators(operators)
        if ((currentOperator !== operator && operators.includes(startingOperator)) || !propertyDefinition) {
            setCurrentOperator(startingOperator)
        } else if (!operators.includes(currentOperator) && propertyDefinition) {
            // Whenever the property type changes such that the operator is not compatible, we need to reset the operator
            // But, only if the propertyDefinition is available
            let defaultProperty = PropertyOperator.Exact
            if (isDateTimeProperty) {
                defaultProperty = PropertyOperator.IsDateExact
            } else if (propertyType === PropertyType.Cohort) {
                defaultProperty = PropertyOperator.In
            }
            setCurrentOperator(defaultProperty)
        }
    }, [propertyDefinition, propertyKey, operator, operatorAllowlist]) // oxlint-disable-line react-hooks/exhaustive-deps
    return (
        <>
            <div data-attr="taxonomic-operator">
                {editable ? (
                    <OperatorSelect
                        operator={currentOperator || PropertyOperator.Exact}
                        operators={operators}
                        onChange={(newOperator: PropertyOperator) => {
                            const tentativeValidationError =
                                newOperator && value ? getRegexValidationError(newOperator, value) : null
                            if (tentativeValidationError) {
                                setValidationError(tentativeValidationError)
                                return
                            }
                            setValidationError(null)

                            setCurrentOperator(newOperator)
                            if (isOperatorCohort(newOperator)) {
                                onChange(newOperator, value || null)
                            } else if (isOperatorRange(newOperator) && isNaN(value as any)) {
                                // If the new operator is range and the value is not a number, we want to set the new value to null
                                onChange(newOperator, null)
                            } else if (isOperatorFlag(newOperator)) {
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
                        size={size}
                        startVisible={startVisible}
                    />
                ) : (
                    <span>{allOperatorsToHumanName(currentOperator)} </span>
                )}
            </div>
            {!isOperatorFlag(currentOperator || PropertyOperator.Exact) && type && propertyKey && (
                <div
                    // High flex-grow for proper sizing within TaxonomicPropertyFilter
                    className="shrink grow-[1000] min-w-[10rem]"
                    data-attr="taxonomic-value-select"
                >
                    <PropertyValue
                        type={type}
                        key={propertyKey}
                        propertyKey={propertyKey}
                        endpoint={endpoint}
                        operator={currentOperator || PropertyOperator.Exact}
                        placeholder={placeholder}
                        value={value}
                        eventNames={eventNames}
                        onSet={(newValue: string | number | string[] | null) => {
                            const tentativeValidationError =
                                currentOperator && newValue
                                    ? getValidationError(currentOperator, newValue, propertyKey)
                                    : null
                            if (tentativeValidationError) {
                                setValidationError(tentativeValidationError)
                                return
                            }
                            setValidationError(null)

                            onChange(currentOperator || PropertyOperator.Exact, newValue)
                        }}
                        // open automatically only if new filter
                        autoFocus={!isMobile() && value === null}
                        addRelativeDateTimeOptions={addRelativeDateTimeOptions}
                        groupTypeIndex={groupTypeIndex}
                        editable={editable}
                        size={size}
                    />
                </div>
            )}
            {validationError && <span className="taxonomic-validation-error">{validationError}</span>}
        </>
    )
}

export function OperatorSelect({
    operator,
    operators,
    onChange,
    className,
    size,
    startVisible,
}: OperatorSelectProps): JSX.Element {
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
            className={className}
            size={size}
            menu={{
                closeParentPopoverOnClickInside: false,
            }}
            startVisible={startVisible}
        />
    )
}
