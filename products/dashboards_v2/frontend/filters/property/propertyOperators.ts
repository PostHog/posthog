import { isOperatorFlag, isOperatorMulti } from 'lib/utils/operators'

import { PropertyOperator, PropertyType } from '~/types'

import { summarizeValues } from '../filterDefinition'

export type OperatorInput = 'list' | 'text' | 'number' | 'none'

export type OperatorOption = {
    operator: PropertyOperator
    label: string
    input: OperatorInput
}

function inputFor(operator: PropertyOperator): OperatorInput {
    if (isOperatorFlag(operator)) {
        return 'none'
    }
    if (isOperatorMulti(operator)) {
        return 'list'
    }
    return operator === PropertyOperator.GreaterThan || operator === PropertyOperator.LessThan ? 'number' : 'text'
}

// The labels are shorter than the app's operator labels, because they sit inside a pill.
const option = (operator: PropertyOperator, label: string): OperatorOption => ({
    operator,
    label,
    input: inputFor(operator),
})

const SET = [option(PropertyOperator.IsSet, 'is set'), option(PropertyOperator.IsNotSet, 'is not set')]

const STRING = [
    option(PropertyOperator.Exact, 'is'),
    option(PropertyOperator.IsNot, 'is not'),
    option(PropertyOperator.IContains, 'contains'),
    option(PropertyOperator.NotIContains, "doesn't contain"),
    option(PropertyOperator.Regex, 'matches'),
    ...SET,
]

const NUMERIC = [
    option(PropertyOperator.Exact, '='),
    option(PropertyOperator.IsNot, '≠'),
    option(PropertyOperator.GreaterThan, '>'),
    option(PropertyOperator.LessThan, '<'),
    ...SET,
]

const DATE = [option(PropertyOperator.IsDateAfter, 'after'), option(PropertyOperator.IsDateBefore, 'before'), ...SET]

const BOOLEAN = [option(PropertyOperator.Exact, 'is'), ...SET]

/** An unknown type is treated as text. */
export function operatorsFor(type: PropertyType | null | undefined): OperatorOption[] {
    switch (type) {
        case PropertyType.Numeric:
            return NUMERIC
        case PropertyType.DateTime:
            return DATE
        case PropertyType.Boolean:
            return BOOLEAN
        default:
            return STRING
    }
}

export type PropertyCondition = {
    operator: PropertyOperator
    value?: string[] | string | number
}

// Blank text is no value, so a cleared input never applies as "is" or "contains" an empty string.
function valuesOf(value: PropertyCondition['value']): string[] {
    if (value === undefined) {
        return []
    }
    const values = Array.isArray(value) ? value : [String(value)]
    return values.filter((candidate) => candidate.trim() !== '')
}

export function isCompleteCondition(condition: PropertyCondition): boolean {
    return isOperatorFlag(condition.operator) || valuesOf(condition.value).length > 0
}

export function describeCondition(
    condition: PropertyCondition,
    options: OperatorOption[]
): { operator: string; value: string } {
    const label = options.find((candidate) => candidate.operator === condition.operator)?.label
    return { operator: label ?? condition.operator, value: summarizeValues(valuesOf(condition.value)) }
}
