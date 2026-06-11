import { useEffect, useMemo, useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { RowFilter, RowFilterOperator } from '~/types'

import {
    ROW_FILTER_OPERATORS,
    RowFilterColumnCategory,
    classifyColumnType,
    isMultiValueOperator,
    rowFilterOperatorLabel,
    validateRowFilters,
} from './rowFilterUtils'

// Shares the column-source shape with the column picker so the editor works for both the
// existing-source schema and the wizard's pre-creation sync schema.
export interface RowFilterTarget {
    id?: string
    name?: string
    row_filters?: RowFilter[] | null
    available_columns?: { name: string; data_type?: string; is_nullable?: boolean }[]
}

interface RowFilterEditorProps {
    schema: RowFilterTarget | null
    onSave?: (rowFilters: RowFilter[] | null) => void
    /** Hide the Save/Reset footer (a parent drives saving itself). */
    hideActions?: boolean
    /** Fires on every edit, so a parent can drive saving with its own button. */
    onChange?: (rowFilters: RowFilter[] | null) => void
}

const DEFAULT_OPERATOR: RowFilterOperator = '='

function defaultValueForCategory(category: RowFilterColumnCategory): string | number | boolean {
    return category === 'boolean' ? true : ''
}

export function RowFilterEditor({ schema, onSave, hideActions, onChange }: RowFilterEditorProps): JSX.Element {
    const available = useMemo(() => schema?.available_columns ?? [], [schema?.available_columns])
    const [filters, setFilters] = useState<RowFilter[]>([])

    useEffect(() => {
        setFilters(Array.isArray(schema?.row_filters) ? schema!.row_filters!.map((f) => ({ ...f })) : [])
        // Stable serialized key: the array ref changes on every poll even with identical contents.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [schema?.id, JSON.stringify(schema?.row_filters ?? null)])

    const errors = useMemo(() => validateRowFilters(filters, { availableColumns: available }), [filters, available])

    const columnOptions = useMemo(
        () =>
            available.map((column) => ({
                value: column.name,
                label: column.name,
                labelInMenu: (
                    <div className="flex items-center gap-2">
                        <code>{column.name}</code>
                        {column.data_type && <span className="text-xs text-muted-alt">{column.data_type}</span>}
                    </div>
                ),
            })),
        [available]
    )

    const update = (next: RowFilter[]): void => {
        setFilters(next)
        onChange?.(next.length ? next : null)
    }

    const categoryFor = (column: string): RowFilterColumnCategory =>
        classifyColumnType(available.find((c) => c.name === column)?.data_type)

    const addFilter = (): void => {
        const firstColumn = available[0]?.name ?? ''
        const category = categoryFor(firstColumn)
        update([
            ...filters,
            { column: firstColumn, operator: DEFAULT_OPERATOR, value: defaultValueForCategory(category) },
        ])
    }

    const removeFilter = (index: number): void => {
        update(filters.filter((_, i) => i !== index))
    }

    const patchFilter = (index: number, patch: Partial<RowFilter>): void => {
        update(
            filters.map((filter, i) => {
                if (i !== index) {
                    return filter
                }
                const merged = { ...filter, ...patch }
                // When the column changes, reset the value if its type category changed so we don't
                // carry, say, a date string onto an integer column.
                if (patch.column && patch.column !== filter.column) {
                    const prevCategory = categoryFor(filter.column)
                    const nextCategory = categoryFor(patch.column)
                    if (prevCategory !== nextCategory) {
                        merged.value = isMultiValueOperator(merged.operator)
                            ? ''
                            : defaultValueForCategory(nextCategory)
                    }
                }
                // Switching between scalar and multi-value operators changes the value shape
                // (single value vs comma-separated list), so reset to a clean string/default.
                if (patch.operator && isMultiValueOperator(patch.operator) !== isMultiValueOperator(filter.operator)) {
                    merged.value = isMultiValueOperator(patch.operator)
                        ? ''
                        : defaultValueForCategory(categoryFor(merged.column))
                }
                return merged
            })
        )
    }

    const hasErrors = Object.keys(errors).length > 0

    return (
        <div className="flex flex-col gap-2">
            {filters.length === 0 && (
                <div className="text-sm text-muted-alt">
                    No row filters. All rows sync. Add a filter to sync only matching rows.
                </div>
            )}
            {filters.map((filter, index) => {
                const category = categoryFor(filter.column)
                return (
                    <div key={index} className="flex flex-col gap-1">
                        <div className="flex items-center gap-2">
                            <LemonSelect
                                className="flex-1"
                                placeholder="Column"
                                value={filter.column || undefined}
                                onChange={(value) => patchFilter(index, { column: value as string })}
                                options={columnOptions}
                            />
                            <LemonSelect
                                value={filter.operator}
                                onChange={(value) => patchFilter(index, { operator: value as RowFilterOperator })}
                                options={ROW_FILTER_OPERATORS.map((op) => ({
                                    value: op,
                                    label: op,
                                    labelInMenu: rowFilterOperatorLabel(op),
                                }))}
                            />
                            <RowFilterValueInput
                                category={category}
                                multiValue={isMultiValueOperator(filter.operator)}
                                value={filter.value}
                                hasError={!!errors[index]}
                                onChange={(value) => patchFilter(index, { value })}
                            />
                            <LemonButton
                                icon={<IconTrash />}
                                size="small"
                                status="danger"
                                onClick={() => removeFilter(index)}
                                tooltip="Remove filter"
                            />
                        </div>
                        {errors[index] && <span className="text-xs text-danger pl-1">{errors[index]}</span>}
                    </div>
                )
            })}
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={addFilter}
                    disabledReason={available.length === 0 ? 'No columns discovered' : undefined}
                >
                    Add filter
                </LemonButton>
            </div>
            {!hideActions && (
                <div className="flex items-center justify-between gap-2 mt-2">
                    <LemonButton
                        type="tertiary"
                        onClick={() => update([])}
                        disabledReason={filters.length === 0 ? 'No filters to clear' : undefined}
                    >
                        Clear all filters
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => onSave?.(filters.length ? filters : null)}
                        disabledReason={hasErrors ? 'Fix the highlighted filters first' : undefined}
                    >
                        Save
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

function RowFilterValueInput({
    category,
    multiValue,
    value,
    hasError,
    onChange,
}: {
    category: RowFilterColumnCategory
    multiValue: boolean
    value: string | number | boolean
    hasError: boolean
    onChange: (value: string | number | boolean) => void
}): JSX.Element {
    // IN / NOT IN take a comma-separated list, so a single text input regardless of type.
    if (multiValue) {
        const example =
            category === 'string'
                ? "'a', 'b', 'c'"
                : category === 'date'
                  ? '2026-01-01, 2026-02-01'
                  : category === 'boolean'
                    ? 'true, false'
                    : '1, 2, 3'
        return (
            <LemonInput
                className="flex-1"
                type="text"
                status={hasError ? 'danger' : 'default'}
                placeholder={`Comma-separated, e.g. ${example}`}
                value={value === undefined || value === null ? '' : String(value)}
                onChange={(v) => onChange(v)}
            />
        )
    }

    if (category === 'boolean') {
        return (
            <LemonSelect
                className="flex-1"
                value={typeof value === 'boolean' ? value : true}
                onChange={(v) => onChange(!!v)}
                options={[
                    { value: true, label: 'true' },
                    { value: false, label: 'false' },
                ]}
            />
        )
    }

    // LemonInput's text variant doesn't support `type="date"`, and its number variant emits a
    // `number` (not string) from onChange — mixing them via a dynamic type breaks the prop union.
    // So everything non-boolean uses a text input; the backend coerces numeric/date/timestamp
    // strings, and `validateRowFilters` checks the format client-side.
    const placeholder =
        category === 'date'
            ? 'YYYY-MM-DD'
            : category === 'timestamp'
              ? 'YYYY-MM-DDTHH:MM:SS'
              : category === 'integer'
                ? 'Whole number'
                : category === 'numeric'
                  ? 'Number'
                  : 'Value'

    return (
        <LemonInput
            className="flex-1"
            type="text"
            status={hasError ? 'danger' : 'default'}
            placeholder={placeholder}
            value={value === undefined || value === null ? '' : String(value)}
            onChange={(v) => onChange(v)}
        />
    )
}
