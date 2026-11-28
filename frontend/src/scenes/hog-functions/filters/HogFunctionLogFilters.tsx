import { LemonField } from 'lib/lemon-ui/LemonField'

import { CyclotronJobFiltersType, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { DropRuleFilterEditor } from 'products/logs/frontend/components/LogsSampling/DropRuleFilterEditor'

const EMPTY_FILTER_GROUP: UniversalFiltersGroup = { type: FilterLogicalOperator.And, values: [] }

// Stored wrapped (`{type, values: [innerGroup]}`) like other logs filter groups; the editor works on the inner group.
function unwrapFilterGroup(stored: UniversalFiltersGroup | undefined): UniversalFiltersGroup {
    const inner = stored?.values?.[0] as UniversalFiltersGroup | undefined
    return inner && Array.isArray(inner.values) ? inner : EMPTY_FILTER_GROUP
}

export function HogFunctionLogFilters(): JSX.Element {
    return (
        <div className="deprecated-space-y-2 rounded border p-3 bg-surface-primary">
            <LemonField
                name="filters"
                label="Filters"
                info="Only log records that match these filters are transformed. Other records pass through unchanged."
            >
                {({ value, onChange }) => {
                    const filters = (value ?? {}) as CyclotronJobFiltersType
                    return (
                        <>
                            <p className="mb-0 text-sm text-secondary">Leave empty to transform every log record.</p>
                            <DropRuleFilterEditor
                                logicKey="hog-function-log-filters"
                                filterGroup={unwrapFilterGroup(filters.filter_group)}
                                onChange={(group) =>
                                    onChange({
                                        ...filters,
                                        filter_group: { type: FilterLogicalOperator.And, values: [group] as never },
                                    })
                                }
                            />
                        </>
                    )
                }}
            </LemonField>
        </div>
    )
}
