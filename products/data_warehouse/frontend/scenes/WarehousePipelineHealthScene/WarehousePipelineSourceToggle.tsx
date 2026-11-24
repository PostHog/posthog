import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'

/** The chevron of a source row. It opens the tables of that source below the table of sources. */
export function WarehousePipelineSourceToggle({
    sourceId,
    sourceName,
}: {
    sourceId: string
    sourceName: string
}): JSX.Element {
    const { expandedSourceId } = useValues(warehousePipelineHealthLogic)
    const { toggleSource } = useActions(warehousePipelineHealthLogic)
    const expanded = expandedSourceId === sourceId

    return (
        <Button
            size="icon-sm"
            aria-expanded={expanded}
            aria-controls="warehouse-pipeline-health-source-tables"
            aria-label={`${expanded ? 'Hide' : 'Show'} tables in ${sourceName}`}
            onClick={() => toggleSource(sourceId)}
            data-attr="warehouse-pipeline-health-source-toggle"
        >
            {expanded ? <IconChevronDown /> : <IconChevronRight />}
        </Button>
    )
}
