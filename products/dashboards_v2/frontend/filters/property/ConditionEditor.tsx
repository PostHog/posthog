import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { type ValueOption, ValueList } from '../ValueList'
import type { OperatorOption } from './propertyOperators'
import { TypedValue } from './TypedValue'
import type { Draft } from './useConditionDrafts'

export function ConditionEditor({
    options,
    draft,
    loadValues,
    onChange,
}: {
    options: OperatorOption[]
    draft: Draft
    loadValues?: (search: string, signal: AbortSignal) => Promise<ValueOption[]>
    onChange: (draft: Draft) => void
}): JSX.Element {
    const option = options.find((candidate) => candidate.operator === draft.operator) ?? options[0]
    const pickOperator = (operator: unknown): void => {
        const next = options.find((candidate) => candidate.operator === operator)
        if (!next) {
            return
        }
        // A value carries over only to an operator that takes the same kind of value.
        const keep = next.input === option.input && next.input !== 'none'
        onChange({ id: draft.id, operator: next.operator, value: keep ? draft.value : undefined })
    }
    return (
        <>
            <Select
                items={options.map(({ operator, label }) => ({ value: operator, label }))}
                value={option.operator}
                onValueChange={pickOperator}
            >
                <SelectTrigger size="sm" className="w-fit" data-attr="dashboard-v2-filter-operator">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {options.map((candidate) => (
                        <SelectItem key={candidate.operator} value={candidate.operator}>
                            {candidate.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            {option.input === 'list' && (
                <ValueList
                    load={loadValues}
                    selected={Array.isArray(draft.value) ? draft.value : []}
                    onChange={(picked) => onChange({ ...draft, value: picked })}
                />
            )}
            {(option.input === 'text' || option.input === 'number') && (
                <TypedValue
                    key={`${draft.id}-${option.operator}`}
                    option={option}
                    value={draft.value}
                    onChange={(next) => onChange({ ...draft, value: next })}
                />
            )}
        </>
    )
}
