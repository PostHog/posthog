import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { DATE_BUCKET_OPTIONS, FILTER_OPERATOR_OPTIONS } from 'products/business_intelligence/frontend/biEditorOptions'
import { isDateTimeBIField, isNumericBIField } from 'products/business_intelligence/frontend/biEditorTypes'
import { BIFilterValueInput } from 'products/business_intelligence/frontend/BIFilterValueInput'

export function BIFilterEditor({ index, onDone }: { index: number; onDone: () => void }): JSX.Element | null {
    const { config } = useValues(biEditorLogic)
    const {
        removeFieldFromShelf,
        setFieldDateBucket,
        setFieldExpression,
        setFilterCustomExpression,
        setFilterOperator,
        updateFilter,
    } = useActions(biEditorLogic)
    const filter = config.filters[index]
    if (!filter) {
        return null
    }

    const { field } = filter
    const needsValue = !['last_7_days', 'is_set', 'is_not_set', 'custom'].includes(filter.operator)

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
                    options={FILTER_OPERATOR_OPTIONS.filter(
                        (option) =>
                            option.value === filter.operator ||
                            ((option.value !== 'last_7_days' || isDateTimeBIField(field)) &&
                                (option.value !== 'between' || isDateTimeBIField(field) || isNumericBIField(field)))
                    )}
                    onChange={(operator) => setFilterOperator(index, operator)}
                    size="small"
                    aria-label={`${field.name} filter condition`}
                    data-attr="bi-filter-condition"
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
                    <BIFilterValueInput index={index} />
                </div>
            ) : null}
            <LemonCheckbox
                checked={filter.enabled !== false}
                onChange={(enabled) => updateFilter(index, { enabled })}
                label="Apply filter"
                size="small"
            />
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
