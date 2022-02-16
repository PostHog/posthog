import { PropertyFilterValue, PropertyOperator } from '~/types'
import { genericOperatorMap } from 'lib/utils'

export function eventToHumanName(event?: string): string {
    return event && event[0] == '$' ? event[1].toUpperCase() + event.slice(2) : event ?? 'Event'
}

export function operatorToHumanName(operator?: string): string {
    if (operator === 'gte') {
        return 'at least'
    }
    if (operator === 'lte') {
        return 'at most'
    }
    return 'exactly'
}

export function genericOperatorToHumanName(operator?: PropertyOperator | null): string {
    if (operator && genericOperatorMap[operator]) {
        return genericOperatorMap[operator].slice(2)
    }
    return 'equals'
}

export function propertyValueToHumanName(value?: PropertyFilterValue): string {
    if (value?.[0]) {
        return value[0]
    }
    if (value === '') {
        return '(empty string)'
    }
    if (!value) {
        return String(value)
    }
    return ''
}
