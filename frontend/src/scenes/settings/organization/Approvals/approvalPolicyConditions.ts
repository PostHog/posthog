// Available fields that can be gated
export const GATEABLE_FIELDS: Record<string, { label: string; type: 'number' | 'boolean' | 'string' }> = {
    rollout_percentage: { label: 'Rollout percentage', type: 'number' },
}

export const CONDITION_TYPES = [
    { value: 'any_change', label: 'changes' },
    { value: 'before_after', label: 'new value is' },
    { value: 'change_amount', label: 'changes by' },
]

export const CONDITION_TYPES_TOOLTIP = `• changes – require approval whenever this field is modified
• new value is – require approval when the new value meets a threshold (e.g., rollout > 50%)
• changes by – require approval when the change amount meets a threshold (e.g., increased by more than 10%)`

export const OPERATORS = [
    { value: '>', label: '>' },
    { value: '>=', label: '>=' },
    { value: '<', label: '<' },
    { value: '<=', label: '<=' },
    { value: '==', label: '=' },
    { value: '!=', label: '≠' },
]

export interface ConditionRule {
    field: string
    type: string
    operator?: string
    value?: number
}
