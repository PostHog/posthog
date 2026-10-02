import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'

import { biEditorLogic } from 'scenes/data-warehouse/editor/bi/biEditorLogic'
import { FILTER_OPERATOR_OPTIONS } from 'scenes/data-warehouse/editor/bi/biEditorOptions'
import { isDateTimeBIField, isNumericBIField } from 'scenes/data-warehouse/editor/bi/biEditorTypes'
import { BIFilterPill } from 'scenes/data-warehouse/editor/bi/components/BIFilterPill'

import { BIFilterValueInput } from './BIFilterValueInput'

export function BIFilterControl({ index }: { index: number }): JSX.Element | null {
    const { config } = useValues(biEditorLogic)
    const { setFilterOperator, updateFilter } = useActions(biEditorLogic)
    const filter = config.filters[index]
    if (!filter) {
        return null
    }
    return (
        <div
            className="flex min-w-0 flex-col gap-2 rounded border bg-surface-primary p-2"
            data-attr="bi-filter-control"
        >
            <BIFilterPill index={index} />
            <LemonSelect
                value={filter.operator}
                options={FILTER_OPERATOR_OPTIONS.filter(
                    (option) =>
                        option.value === filter.operator ||
                        ((option.value !== 'last_7_days' || isDateTimeBIField(filter.field)) &&
                            (option.value !== 'between' ||
                                isDateTimeBIField(filter.field) ||
                                isNumericBIField(filter.field)))
                )}
                onChange={(operator) => setFilterOperator(index, operator)}
                size="small"
                fullWidth
                aria-label={`${filter.field.name} filter condition`}
                data-attr="bi-filter-condition"
            />
            <BIFilterValueInput index={index} />
            <LemonCheckbox
                checked={filter.enabled !== false}
                onChange={(enabled) => updateFilter(index, { enabled })}
                label="Apply filter"
                size="small"
                data-attr="bi-filter-enabled"
            />
        </div>
    )
}
