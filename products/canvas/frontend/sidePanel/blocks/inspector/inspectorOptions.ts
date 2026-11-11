import type { InspectorOption } from './OptionSelect'

export type MathValue = 'total' | 'dau' | 'weekly_active' | 'monthly_active'

export const MATH_OPTIONS: InspectorOption<MathValue>[] = [
    { value: 'total', label: 'Total count' },
    { value: 'dau', label: 'Unique users' },
    { value: 'weekly_active', label: 'Weekly active users' },
    { value: 'monthly_active', label: 'Monthly active users' },
]

export const NUMBER_FORMATS: InspectorOption[] = [
    { value: 'number', label: 'Number' },
    { value: 'percent', label: 'Percent' },
    { value: 'currency', label: 'Currency' },
    { value: 'duration', label: 'Duration' },
]

export const WIDTHS: InspectorOption[] = [
    { value: 'normal', label: 'Normal' },
    { value: 'wide', label: 'Wide' },
    { value: 'full', label: 'Full' },
]
