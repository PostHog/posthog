import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, QuickFilterOption } from '~/types'

import { allowedOperators, operatorsWithoutValues, quickFilterFormLogic } from './quickFilterFormLogic'
import { quickFiltersLogic } from './quickFiltersLogic'
import { quickFiltersModalLogic } from './quickFiltersModalLogic'

interface QuickFilterFormProps {
    context: QuickFilterContext
}

export function QuickFilterForm({ context }: QuickFilterFormProps): JSX.Element {
    const modalLogic = quickFiltersModalLogic({ context })
    const { editedFilter } = useValues(modalLogic)
    const formLogic = quickFilterFormLogic({ context, filter: editedFilter })
    const { handleFormBack } = useActions(modalLogic)
    const { quickFiltersLoading } = useValues(quickFiltersLogic({ context }))
    const { name, propertyName, options, isQuickFilterSubmitting } = useValues(formLogic)
    const { addOption } = useActions(formLogic)

    return (
        <Form
            logic={quickFilterFormLogic}
            props={{ context, filter: editedFilter }}
            formKey="quickFilter"
            enableFormOnSubmit
        >
            <div className="space-y-6">
                <div className="flex gap-4">
                    <div className="flex-1">
                        <LemonField name="name" label="Filter name">
                            <LemonInput placeholder="e.g. Environment" disabled={quickFiltersLoading} autoFocus />
                        </LemonField>
                    </div>
                    <div className="flex-1">
                        <LemonField name="propertyName" label="Event property">
                            {({ value, onChange }) => (
                                <TaxonomicPopover
                                    groupType={TaxonomicFilterGroupType.EventProperties}
                                    value={value}
                                    onChange={onChange}
                                    groupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                    placeholder="Select property..."
                                    disabled={quickFiltersLoading}
                                    type="secondary"
                                    fullWidth
                                />
                            )}
                        </LemonField>
                    </div>
                </div>

                {propertyName && (
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="block font-medium">Filter options</label>
                            <LemonButton
                                data-attr="quick-filter-form-add-option-button"
                                size="small"
                                type="secondary"
                                icon={<IconPlus />}
                                onClick={addOption}
                            >
                                Add option
                            </LemonButton>
                        </div>
                        <div className="space-y-2">
                            {options.map((option: QuickFilterOption, index: number) => (
                                <FilterOptionRow key={option.id} option={option} index={index} context={context} />
                            ))}
                        </div>
                    </div>
                )}

                <div className="border rounded p-4 bg-bg-3000">
                    <div className="text-xs font-semibold uppercase text-muted mb-2">Preview</div>
                    <LemonSelect
                        value={null}
                        options={[
                            { value: null, label: `Any ${name?.toLowerCase() || 'items'}` },
                            ...options.map((opt: QuickFilterOption) => ({
                                value: opt.id,
                                label: opt.label,
                            })),
                        ]}
                        size="small"
                        placeholder={name || 'Filter name'}
                        dropdownMatchSelectWidth={false}
                        allowClear
                    />
                </div>

                <div className="flex justify-between gap-2 pt-4 border-t">
                    <LemonButton
                        data-attr="quick-filter-form-back-button"
                        type="secondary"
                        onClick={handleFormBack}
                        disabled={quickFiltersLoading}
                    >
                        Back
                    </LemonButton>
                    <LemonButton
                        data-attr="quick-filter-form-submit-button"
                        type="primary"
                        htmlType="submit"
                        loading={quickFiltersLoading || isQuickFilterSubmitting}
                    >
                        {editedFilter ? 'Update filter' : 'Create filter'}
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}

function FilterOptionRow({
    option,
    index,
    context,
}: {
    option: QuickFilterOption
    index: number
    context: QuickFilterContext
}): JSX.Element {
    const { editedFilter } = useValues(quickFiltersModalLogic({ context }))
    const { quickFiltersLoading } = useValues(quickFiltersLogic({ context }))
    const { propertyName, options, quickFilterErrors } = useValues(
        quickFilterFormLogic({ context, filter: editedFilter })
    )
    const { updateOption, removeOption } = useActions(quickFilterFormLogic({ context, filter: editedFilter }))
    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)

    const propertyDefinitions = propertyDefinitionsByType(PropertyFilterType.Event)

    const optionErrors = quickFilterErrors?.options as Record<string, string>[] | undefined
    const rowErrors = optionErrors?.[index]

    return (
        <div className="flex gap-2 items-start">
            <div className="flex-1 flex gap-2 flex-col">
                <div className="flex gap-2">
                    <OperatorValueSelect
                        type={PropertyFilterType.Event}
                        propertyKey={propertyName}
                        operator={option.operator || PropertyOperator.Exact}
                        value={option.value}
                        editable={!quickFiltersLoading && !!propertyName}
                        onChange={(operator, value) => {
                            let newValue: string | string[] | null = null
                            if (operatorsWithoutValues.includes(operator)) {
                                newValue = null
                            } else if (typeof value === 'string') {
                                newValue = value
                            } else if (Array.isArray(value)) {
                                newValue = value.map(String)
                            } else if (value !== null && value !== undefined) {
                                newValue = String(value)
                            }
                            updateOption(index, { operator, value: newValue })
                        }}
                        propertyDefinitions={propertyDefinitions}
                        operatorAllowlist={allowedOperators}
                        size="small"
                    />
                </div>
                {rowErrors?.value && <LemonField.Error error={rowErrors.value} />}
            </div>
            <div className="flex flex-col w-[30%] gap-2">
                <LemonInput
                    value={option.label}
                    onChange={(value) => updateOption(index, { label: value })}
                    placeholder="Display name (e.g., Production)"
                    disabledReason={!propertyName ? 'Select an event property first' : undefined}
                />
                {rowErrors?.label && <LemonField.Error error={rowErrors.label} />}
            </div>
            {options.length > 1 && (
                <LemonButton
                    size="small"
                    status="danger"
                    icon={<IconTrash />}
                    onClick={() => removeOption(index)}
                    disabled={quickFiltersLoading}
                />
            )}
        </div>
    )
}
