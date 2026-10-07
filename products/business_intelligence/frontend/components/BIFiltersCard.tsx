import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { BIFilterPill } from 'products/business_intelligence/frontend/components/BIFilterPill'
import { BIShelfCard } from 'products/business_intelligence/frontend/components/BIShelfCard'
import { BIShelfDropTarget } from 'products/business_intelligence/frontend/components/BIShelfDropTarget'

export function BIFiltersCard(): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { addBlankFieldToShelf } = useActions(biEditorLogic)

    return (
        <BIShelfCard title="Filters">
            <BIShelfDropTarget shelf="filters" className="flex min-h-6 flex-col gap-0.5">
                {config.filters.length > 0 ? (
                    config.filters.map((filter, index) => <BIFilterPill key={filter.field.id} index={index} />)
                ) : (
                    <span className="p-1 text-xs text-tertiary">Drop fields here to filter rows</span>
                )}
            </BIShelfDropTarget>
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
        </BIShelfCard>
    )
}
