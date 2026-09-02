import { ListVariable } from '../../types'

export type RelativeDateUnit = 'h' | 'd' | 'w' | 'm' | 'y'

export interface RelativeDateValue {
    amount: number
    unit: RelativeDateUnit
}

export const coerceListVariableValue = (value: unknown): string | null => {
    if (value == null) {
        return null
    }
    if (typeof value === 'string') {
        return value
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
    }
    if (typeof value === 'object' && !Array.isArray(value)) {
        const record = value as Record<string, unknown>
        for (const key of ['value', 'label']) {
            const inner = record[key]
            if (typeof inner === 'string') {
                return inner
            }
            if (typeof inner === 'number' || typeof inner === 'boolean') {
                return String(inner)
            }
        }
    }
    try {
        return JSON.stringify(value) ?? null
    } catch {
        return String(value)
    }
}

export const getListVariableValues = (variable: ListVariable): string[] =>
    Array.isArray(variable.values)
        ? variable.values.map(coerceListVariableValue).filter((value): value is string => value !== null)
        : []

export const getListVariableSelectedValues = (variable: ListVariable): string[] => {
    const selectedValue = variable.value ?? variable.default_value
    const rawValues = Array.isArray(selectedValue) ? selectedValue : [selectedValue]
    const selectedValues = rawValues
        .map(coerceListVariableValue)
        .filter((value): value is string => value !== null && value !== '')

    return variable.is_multi ? selectedValues : selectedValues.slice(0, 1)
}

export const normalizeRelativeDateAmount = (amount: unknown): number => {
    const parsedAmount = Number(amount)
    return Number.isFinite(parsedAmount) ? Math.max(0, Math.round(parsedAmount)) : 0
}

// Keep in sync with parseRelativeDateValue — the backend resolves a wider grammar
// (see is_relative_date_value in posthog/hogql/variables.py), but values this UI
// can't parse must not open the relative editor, which would rewrite them on edit.
export const isRelativeDateValue = (value: string): boolean => /^-\d+[hdwmy]$/.test(value)

export const parseRelativeDateValue = (value: string): RelativeDateValue | null => {
    const match = value.match(/^-(\d+)([hdwmy])$/)
    if (!match) {
        return null
    }

    return {
        amount: Number(match[1]),
        unit: match[2] as RelativeDateUnit,
    }
}

export const formatRelativeDateValue = (value: string): string => {
    const parsedValue = parseRelativeDateValue(value)
    if (!parsedValue) {
        return value
    }
    if (parsedValue.amount === 0) {
        return 'Now'
    }

    const unitLabels: Record<RelativeDateUnit, string> = {
        h: 'hour',
        d: 'day',
        w: 'week',
        m: 'month',
        y: 'year',
    }
    const unit = unitLabels[parsedValue.unit]
    return `${parsedValue.amount} ${unit}${parsedValue.amount === 1 ? '' : 's'} ago`
}
