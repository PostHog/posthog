import { useValues } from 'kea'

import { biEditorLogic } from '../biEditorLogic'
import { BIFilterPill } from './BIFilterPill'
import { BIShelfCard } from './BIShelfCard'
import { BIShelfDropTarget } from './BIShelfDropTarget'

export function BIFiltersCard(): JSX.Element {
    const { config } = useValues(biEditorLogic)

    return (
        <BIShelfCard title="Filters">
            <BIShelfDropTarget shelf="filters" className="flex min-h-12 flex-col gap-1 border border-dashed p-1">
                {config.filters.length > 0 ? (
                    config.filters.map((filter, index) => <BIFilterPill key={filter.field.id} index={index} />)
                ) : (
                    <span className="p-1 text-xs text-tertiary">Drop fields here to filter rows</span>
                )}
            </BIShelfDropTarget>
        </BIShelfCard>
    )
}
