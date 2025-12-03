import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

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
    const { name, propertyName, options, isValid } = useValues(formLogic)
    const { setName, setPropertyName, addOption, submitForm } = useActions(formLogic)

    return (
        <div className="space-y-6">
            <div className="flex gap-4">
                <div className="flex-1">
                    <label className="block font-medium mb-2">Filter name</label>
                    <LemonInput
                        value={name}
                        onChange={setName}
                        placeholder="e.g. Environment"
                        disabled={quickFiltersLoading}
                        autoFocus
                    />
                </div>
                <div className="flex-1">
                    <label className="block font-medium mb-2">Event property</label>
                    <TaxonomicPopover
                        groupType={TaxonomicFilterGroupType.EventProperties}
                        value={propertyName}
                        onChange={(value) => setPropertyName(value)}
                        groupTypes={[TaxonomicFilterGroupType.EventProperties]}
                        placeholder="Select property..."
                        disabled={quickFiltersLoading}
                        type="secondary"
                        fullWidth
                    />
                </div>
            </div>

            {propertyName && (
                <div>
                    <div className="flex items-center justify-between mb-2">
                        <label className="block font-medium">Filter options</label>
                        <LemonButton size="small" type="secondary" icon={<IconPlus />} onClick={addOption}>
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
                <LemonButton type="secondary" onClick={handleFormBack} disabled={quickFiltersLoading}>
                    Back
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={submitForm}
                    loading={quickFiltersLoading}
                    disabledReason={!isValid ? 'Please fill in all required fields' : undefined}
                >
                    {editedFilter ? 'Update filter' : 'Create filter'}
                </LemonButton>
            </div>
        </div>
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
    const { propertyName, options } = useValues(quickFilterFormLogic({ context, filter: editedFilter }))
    const { updateOption, removeOption } = useActions(quickFilterFormLogic({ context, filter: editedFilter }))
    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)

    const propertyDefinitions = propertyDefinitionsByType(PropertyFilterType.Event)

    return (
        <div className="flex gap-2 items-center">
            <div className="flex-1 flex gap-2">
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
            <LemonInput
                value={option.label}
                onChange={(value) => updateOption(index, { label: value })}
                placeholder="Display name (e.g., Production)"
                disabledReason={!propertyName ? 'Select an event property first' : undefined}
                className="w-[30%]"
            />
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
