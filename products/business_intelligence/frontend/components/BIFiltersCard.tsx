import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInputSelect } from '@posthog/lemon-ui'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'

import { getBIFilterSummary } from '../biEditorTypes'
import { getBIFilterLabel } from '../biFilterSummary'
import { BIConditionGroups } from './BIConditionGroups'
import { BIFilterPill } from './BIFilterPill'
import { BIResultFiltersCard } from './BIResultFiltersCard'
import { BIShelfDropTarget } from './BIShelfDropTarget'

export function BIFiltersCard(): JSX.Element {
    const [resultFiltersOpen, setResultFiltersOpen] = useState(false)
    const [fieldPickerOpen, setFieldPickerOpen] = useState(false)
    const { config, dataPaneFields, dataPaneFieldsLoading } = useValues(biEditorLogic)
    const { addBlankFieldToShelf, addFieldToShelf, setFilterGroup } = useActions(biEditorLogic)
    const filterFields = [...dataPaneFields.dimensions, ...dataPaneFields.measures].filter(
        (field) => !(field.localDefinition?.kind === 'expression' && field.localDefinition.aggregate)
    )

    return (
        <BIShelfDropTarget
            shelf="filters"
            className="flex min-h-9 flex-wrap items-center gap-1 rounded-none border-b px-2 py-1"
        >
            <span className="flex items-center gap-1 text-xs font-semibold text-secondary">
                <IconFilter />
                Row filters
            </span>
            {config.filters.map((filter, index) => (
                <BIFilterPill key={filter.field.id} index={index} />
            ))}
            <LemonDropdown
                visible={fieldPickerOpen}
                onVisibilityChange={setFieldPickerOpen}
                closeOnClickInside={false}
                placement="bottom-start"
                overlay={
                    <div className="flex w-64 flex-col gap-2">
                        <LemonInputSelect
                            mode="single"
                            value={[]}
                            options={filterFields.map((field) => ({ key: field.id, label: field.label ?? field.name }))}
                            loading={dataPaneFieldsLoading}
                            placeholder="Search table fields"
                            autoFocus
                            fullWidth
                            onChange={([id]) => {
                                const field = filterFields.find((candidate) => candidate.id === id)
                                if (field) {
                                    addFieldToShelf(field, 'filters')
                                    setFieldPickerOpen(false)
                                }
                            }}
                            data-attr="bi-filter-field-picker"
                        />
                        <LemonButton
                            size="xsmall"
                            onClick={() => {
                                addBlankFieldToShelf('filters')
                                setFieldPickerOpen(false)
                            }}
                        >
                            Custom SQL expression
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton
                    icon={<IconPlus />}
                    size="xsmall"
                    type="tertiary"
                    disabledReason={!config.source ? 'Select a data source first' : undefined}
                    data-attr="bi-editor-filters-add-field"
                >
                    Add filter
                </LemonButton>
            </LemonDropdown>
            {config.filters.length > 1 && (
                <BIConditionGroups
                    title="Row filter groups"
                    group={config.rowFilterGroup}
                    options={config.filters.map((filter) => ({
                        value: filter.field.id,
                        label: `${getBIFilterLabel(filter)}: ${getBIFilterSummary(filter)}`,
                    }))}
                    onChange={(group) => setFilterGroup('row', group)}
                />
            )}
            <LemonDropdown
                visible={resultFiltersOpen}
                onVisibilityChange={setResultFiltersOpen}
                closeOnClickInside={false}
                placement="bottom-end"
                overlay={
                    <div className="relative w-72">
                        <div className="absolute right-1 top-1 z-10">
                            <LemonButton
                                icon={<IconX />}
                                type="tertiary"
                                size="xsmall"
                                aria-label="Close result filters"
                                onClick={() => setResultFiltersOpen(false)}
                            />
                        </div>
                        <BIResultFiltersCard />
                    </div>
                }
            >
                <LemonButton size="xsmall" type="tertiary" className="ml-auto" data-attr="bi-editor-result-filters">
                    <span>Result filters{config.resultFilters?.length ? ` (${config.resultFilters.length})` : ''}</span>
                </LemonButton>
            </LemonDropdown>
        </BIShelfDropTarget>
    )
}
