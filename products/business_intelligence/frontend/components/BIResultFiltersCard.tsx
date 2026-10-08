import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { BIResultFilter } from '~/queries/schema/schema-business-intelligence'

import { biEditorLogic } from '../biEditorLogic'
import { getBIResultFilterValidationError, getBIValuePillLabel } from '../biEditorTypes'
import { BIConditionGroups } from './BIConditionGroups'
import { BIShelfCard } from './BIShelfCard'

const OPERATORS: { value: BIResultFilter['operator']; label: string }[] = [
    { value: 'greater_than', label: 'Greater than' },
    { value: 'greater_than_or_equal', label: 'At least' },
    { value: 'less_than', label: 'Less than' },
    { value: 'less_than_or_equal', label: 'At most' },
    { value: 'equals', label: 'Equals' },
    { value: 'not_equals', label: 'Does not equal' },
    { value: 'between', label: 'Between (inclusive)' },
    { value: 'is_set', label: 'Is set' },
    { value: 'is_not_set', label: 'Is not set' },
]

function ResultFilterEditor({ filter }: { filter: BIResultFilter }): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { updateResultFilter, removeResultFilter } = useActions(biEditorLogic)
    const error = getBIResultFilterValidationError(config, filter)
    return (
        <div className="flex w-64 max-w-full flex-col gap-2 p-2">
            <LemonCheckbox
                label="Apply result filter"
                labelClassName="text-xs"
                checked={filter.enabled !== false}
                onChange={(enabled) => updateResultFilter(filter.id, { enabled })}
            />
            <LemonSelect
                fullWidth
                size="small"
                value={filter.measureIndex}
                options={
                    config.values.length
                        ? config.values.map((value, index) => ({ value: index, label: getBIValuePillLabel(value) }))
                        : [{ value: 0, label: 'Count' }]
                }
                onChange={(measureIndex) => updateResultFilter(filter.id, { measureIndex })}
            />
            <LemonSelect
                fullWidth
                size="small"
                value={filter.operator}
                options={OPERATORS}
                onChange={(operator) => updateResultFilter(filter.id, { operator })}
            />
            {!['is_set', 'is_not_set'].includes(filter.operator) && (
                <LemonInput
                    size="small"
                    aria-label="Result filter value"
                    placeholder={filter.operator === 'between' ? 'Minimum' : 'Value'}
                    value={filter.value}
                    status={error ? 'danger' : 'default'}
                    onChange={(value) => updateResultFilter(filter.id, { value })}
                />
            )}
            {filter.operator === 'between' && (
                <LemonInput
                    size="small"
                    aria-label="Result filter maximum"
                    placeholder="Maximum"
                    value={filter.valueTo ?? ''}
                    status={error ? 'danger' : 'default'}
                    onChange={(valueTo) => updateResultFilter(filter.id, { valueTo })}
                />
            )}
            {error && (
                <span role="alert" className="text-xs text-danger">
                    {error}
                </span>
            )}
            <LemonButton size="small" status="danger" onClick={() => removeResultFilter(filter.id)}>
                Remove filter
            </LemonButton>
        </div>
    )
}

export function BIResultFiltersCard(): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { addResultFilter, setFilterGroup } = useActions(biEditorLogic)
    const label = (filter: BIResultFilter): string =>
        `${config.values[filter.measureIndex] ? getBIValuePillLabel(config.values[filter.measureIndex]) : 'Count'} ${OPERATORS.find((operator) => operator.value === filter.operator)?.label.toLowerCase()} ${filter.value}${filter.operator === 'between' ? ` and ${filter.valueTo ?? ''}` : ''}`
    return (
        <BIShelfCard title="Result filters">
            <p className="mb-1 text-xs text-secondary">Filter measures after aggregation and table calculations.</p>
            <div className="flex min-w-0 flex-col gap-1">
                {config.resultFilters?.map((filter) => (
                    <LemonDropdown
                        key={filter.id}
                        closeOnClickInside={false}
                        placement="right-start"
                        overlay={<ResultFilterEditor filter={filter} />}
                    >
                        <LemonButton
                            size="xsmall"
                            fullWidth
                            status={getBIResultFilterValidationError(config, filter) ? 'danger' : undefined}
                            tooltip={label(filter)}
                            data-attr="bi-result-filter"
                        >
                            <span className="min-w-0 truncate">
                                {filter.enabled === false ? 'Off · ' : ''}
                                {label(filter)}
                            </span>
                        </LemonButton>
                    </LemonDropdown>
                ))}
            </div>
            <LemonButton
                size="xsmall"
                disabledReason={!config.source ? 'Select a data source first' : undefined}
                onClick={addResultFilter}
                data-attr="bi-add-result-filter"
            >
                Add result filter
            </LemonButton>
            <BIConditionGroups
                title="Result filter groups"
                group={config.resultFilterGroup}
                options={(config.resultFilters ?? []).map((filter) => ({ value: filter.id, label: label(filter) }))}
                onChange={(group) => setFilterGroup('result', group)}
            />
            {!!config.resultFilters?.length &&
                (config.totals?.rows || config.totals?.columns || config.totals?.subtotals) && (
                    <p className="text-xs text-secondary">Totals still include all groups matching the row filters.</p>
                )}
        </BIShelfCard>
    )
}
