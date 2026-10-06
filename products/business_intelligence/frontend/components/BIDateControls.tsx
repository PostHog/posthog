import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { getBIComparisonDisabledReason } from '../biComparison'
import { biEditorLogic } from '../biEditorLogic'
import { BI_DATE_OPTIONS } from '../biEditorOptions'
import { isDateTimeBIField } from '../biEditorTypes'
import { getBIDateField } from '../biQueryFilters'

export function BIDateControls(): JSX.Element {
    const { config, dataPaneFields } = useValues(biEditorLogic)
    const { setDateField, setDateRange, setCompareFilter } = useActions(biEditorLogic)
    const dateField = getBIDateField(config)
    const dateFields = dataPaneFields.dimensions.filter(isDateTimeBIField)
    if (dateField && !dateFields.some((field) => field.expression === dateField.expression)) {
        dateFields.unshift(dateField)
    }

    return (
        <div className="flex flex-wrap items-center gap-1" data-attr="bi-editor-date-controls">
            <LemonSelect
                size="small"
                type="tertiary"
                value={dateField?.expression ?? null}
                options={[
                    { value: null, label: 'No date column' },
                    ...dateFields.map((field) => ({ value: field.expression, label: field.name })),
                ]}
                onChange={(expression) =>
                    setDateField(dateFields.find((field) => field.expression === expression) ?? null)
                }
                renderButtonContent={(option) => `Date: ${option?.label}`}
                tooltip="The dashboard date range applies to this column and overrides the worksheet range."
                aria-label="Dashboard date column"
                data-attr="bi-editor-date-field"
            />
            <DateFilter
                size="small"
                type="tertiary"
                dateFrom={config.dateRange?.date_from ?? 'all'}
                dateTo={config.dateRange?.date_to ?? null}
                explicitDate={config.dateRange?.explicitDate ?? false}
                onChange={(date_from, date_to, explicitDate) => setDateRange({ date_from, date_to, explicitDate })}
                disabledReason={!dateField ? 'Select a date column first' : undefined}
                dateOptions={BI_DATE_OPTIONS}
                allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
                allowTimePrecision
                allowFixedRangeWithTime
                showExplicitDateToggle
                makeLabel={(label) => (
                    <>
                        <IconCalendar />
                        <span>{label}</span>
                    </>
                )}
            />
            <CompareFilter
                compareFilter={config.compareFilter}
                updateCompareFilter={setCompareFilter}
                disableReason={getBIComparisonDisabledReason(config)}
            />
        </div>
    )
}
