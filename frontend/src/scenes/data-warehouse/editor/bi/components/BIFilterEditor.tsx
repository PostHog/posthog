import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import { biEditorLogic } from '../biEditorLogic'
import { DATE_BUCKET_OPTIONS, FILTER_OPERATOR_OPTIONS } from '../biEditorOptions'
import { isDateTimeBIField } from '../biEditorTypes'

export function BIFilterEditor({ index, onDone }: { index: number; onDone: () => void }): JSX.Element | null {
    const { config } = useValues(biEditorLogic)
    const {
        removeFieldFromShelf,
        setFieldDateBucket,
        setFieldExpression,
        setFilterCustomExpression,
        setFilterOperator,
        setFilterValue,
    } = useActions(biEditorLogic)
    const filter = config.filters[index]
    if (!filter) {
        return null
    }

    const { field } = filter
    const needsValue = !['last_7_days', 'is_set', 'is_not_set', 'custom'].includes(filter.operator)
    const includesTime = field.type === 'datetime'
    const selectedDate = filter.value && dayjs(filter.value).isValid() ? dayjs(filter.value) : null

    return (
        <div className="flex w-80 flex-col gap-3 p-1">
            <div className="flex flex-col gap-1">
                <LemonLabel>Field</LemonLabel>
                <HogQLDropdown
                    hogQLValue={field.expression}
                    onHogQLValueChange={(expression) => setFieldExpression('filters', index, expression)}
                    tableName={field.source.table}
                    connectionId={field.source.connectionId}
                    size="small"
                    buttonIcon={<IconPencil />}
                    buttonLabel={
                        field.expression ? <code className="truncate">{field.expression}</code> : 'Select field'
                    }
                    buttonAriaLabel={`Edit field expression for ${field.name || 'field'}`}
                />
            </div>
            {isDateTimeBIField(field) ? (
                <div className="flex flex-col gap-1">
                    <LemonLabel>Date part</LemonLabel>
                    <LemonSelect
                        value={field.dateBucket ?? null}
                        options={DATE_BUCKET_OPTIONS}
                        onChange={(dateBucket) => setFieldDateBucket('filters', index, dateBucket)}
                        size="small"
                        data-attr="bi-editor-date-bucket"
                    />
                </div>
            ) : null}
            <div className="flex flex-col gap-1">
                <LemonLabel>Condition</LemonLabel>
                <LemonSelect
                    value={filter.operator}
                    options={FILTER_OPERATOR_OPTIONS.map((option) => ({
                        ...option,
                        disabledReason:
                            option.value === 'last_7_days' && !isDateTimeBIField(field)
                                ? 'Choose a date or date-time field'
                                : undefined,
                    }))}
                    onChange={(operator) => setFilterOperator(index, operator)}
                    size="small"
                />
            </div>
            {filter.operator === 'custom' ? (
                <div className="flex flex-col gap-1">
                    <LemonLabel>SQL condition</LemonLabel>
                    <HogQLDropdown
                        hogQLValue={filter.customExpression ?? ''}
                        onHogQLValueChange={(customExpression) => setFilterCustomExpression(index, customExpression)}
                        tableName={field.source.table}
                        connectionId={field.source.connectionId}
                        size="small"
                        buttonIcon={<IconPencil />}
                        buttonLabel={
                            filter.customExpression ? (
                                <code className="truncate">{filter.customExpression}</code>
                            ) : (
                                'Add SQL condition'
                            )
                        }
                        buttonAriaLabel="Edit filter SQL condition"
                    />
                </div>
            ) : needsValue ? (
                <div className="flex flex-col gap-1">
                    <LemonLabel>Value</LemonLabel>
                    {isDateTimeBIField(field) ? (
                        <LemonCalendarSelectInput
                            value={selectedDate}
                            onChange={(date) =>
                                setFilterValue(
                                    index,
                                    date?.format(includesTime ? 'YYYY-MM-DD HH:mm:ss' : 'YYYY-MM-DD') ?? ''
                                )
                            }
                            granularity={includesTime ? 'minute' : 'day'}
                            format={includesTime ? 'MMM D, YYYY HH:mm' : 'MMM D, YYYY'}
                            use24HourFormat
                            clearable
                            placeholder={includesTime ? 'Select date and time' : 'Select date'}
                            buttonProps={{ size: 'small', 'aria-label': `${field.name} filter date` }}
                        />
                    ) : (
                        <LemonInput
                            value={filter.value}
                            onChange={(value) => setFilterValue(index, value)}
                            onPressEnter={onDone}
                            placeholder="Value"
                            aria-label={`${field.name} filter value`}
                            size="small"
                            autoFocus
                        />
                    )}
                </div>
            ) : null}
            <div className="flex justify-between gap-2">
                <LemonButton
                    type="tertiary"
                    status="danger"
                    size="small"
                    onClick={() => {
                        removeFieldFromShelf('filters', index)
                        onDone()
                    }}
                >
                    Remove filter
                </LemonButton>
                <LemonButton type="primary" size="small" onClick={onDone} data-attr="bi-editor-filter-done">
                    Done
                </LemonButton>
            </div>
        </div>
    )
}
