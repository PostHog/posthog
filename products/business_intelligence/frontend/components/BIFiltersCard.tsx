import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'

import { getBIFieldPillLabel, getBIFilterSummary } from '../biEditorTypes'
import { BIConditionGroups } from './BIConditionGroups'
import { BIFilterPill } from './BIFilterPill'
import { BIResultFiltersCard } from './BIResultFiltersCard'
import { BIShelfDropTarget } from './BIShelfDropTarget'

export function BIFiltersCard(): JSX.Element {
    const [resultFiltersOpen, setResultFiltersOpen] = useState(false)
    const { config } = useValues(biEditorLogic)
    const { addBlankFieldToShelf, setFilterGroup } = useActions(biEditorLogic)

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
            <LemonButton
                icon={<IconPlus />}
                size="xsmall"
                type="tertiary"
                disabledReason={!config.source ? 'Select a data source first' : undefined}
                onClick={() => addBlankFieldToShelf('filters')}
                data-attr="bi-editor-filters-add-field"
            >
                Add filter
            </LemonButton>
            {config.filters.length > 1 && (
                <BIConditionGroups
                    title="Row filter groups"
                    group={config.rowFilterGroup}
                    options={config.filters.map((filter) => ({
                        value: filter.field.id,
                        label: `${getBIFieldPillLabel(filter.field)}: ${getBIFilterSummary(filter)}`,
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
                    <div className="w-72">
                        <div className="flex justify-end">
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
