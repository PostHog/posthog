import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import type { OptionsLoader } from '../useSearchedOptions'
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
    loadValues?: OptionsLoader<ValueOption>
    onChange: (draft: Draft) => void
}): JSX.Element {
    // A draft made before the property's type loaded can hold an operator the type does not offer. The first offered
    // one shows instead, and is the one a value is saved with.
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
                    onChange={(picked) => onChange({ ...draft, operator: option.operator, value: picked })}
                />
            )}
            {(option.input === 'text' || option.input === 'number') && (
                <TypedValue
                    key={`${draft.id}-${option.operator}`}
                    option={option}
                    value={draft.value}
                    onChange={(next) => onChange({ ...draft, operator: option.operator, value: next })}
                />
            )}
        </>
    )
}
