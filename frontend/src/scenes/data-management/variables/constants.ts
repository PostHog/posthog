import {
    formatVariableReference as sharedFormatVariableReference,
    getCodeName as sharedGetCodeName,
    VARIABLE_TYPE_OPTIONS as sharedVariableTypeOptions,
} from '~/queries/nodes/DataVisualization/Components/Variables/VariableFields'
import { VariableType } from '~/queries/nodes/DataVisualization/types'

// Re-export from shared location
export const VARIABLE_TYPE_OPTIONS = sharedVariableTypeOptions
export const formatVariableReference = sharedFormatVariableReference
export const getCodeName = sharedGetCodeName

export const VARIABLE_TYPE_LABELS: Record<VariableType, string> = Object.fromEntries(
    VARIABLE_TYPE_OPTIONS.map((opt) => [opt.value, opt.label])
) as Record<VariableType, string>

export const DELETE_VARIABLE_DESCRIPTION =
    'Are you sure you want to delete this variable? This cannot be undone. Queries that use this variable will no longer work.'
