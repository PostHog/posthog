import { VariableType } from '~/queries/nodes/DataVisualization/types'

export const VARIABLE_TYPE_OPTIONS: Array<{ value: VariableType; label: string }> = [
    { value: 'String', label: 'String' },
    { value: 'Number', label: 'Number' },
    { value: 'Boolean', label: 'Boolean' },
    { value: 'List', label: 'List' },
    { value: 'Date', label: 'Date' },
]

export const VARIABLE_TYPE_LABELS: Record<VariableType, string> = Object.fromEntries(
    VARIABLE_TYPE_OPTIONS.map((opt) => [opt.value, opt.label])
) as Record<VariableType, string>

export const formatVariableReference = (codeName: string): string => `{variables.${codeName}}`
