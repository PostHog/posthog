import { useActions, useValues } from 'kea'

import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { HealthFilter, modelsListLogic } from './modelsListLogic'
import { ISSUE_KIND_ORDER, ISSUE_LABELS } from './overviewIssueCopy'

const FILTER_LABELS: Record<HealthFilter, string> = { attention: 'Needs attention', ...ISSUE_LABELS, all: 'All' }

function isHealthFilter(value: string | undefined): value is HealthFilter {
    return value !== undefined && value in FILTER_LABELS
}

export function ModelsListHealthFilter(): JSX.Element | null {
    const { healthCounts, activeHealthFilter } = useValues(modelsListLogic)
    const { setHealthFilter } = useActions(modelsListLogic)

    if (healthCounts.attention === 0) {
        return null
    }

    const presentKinds = ISSUE_KIND_ORDER.filter((kind) => healthCounts[kind] > 0)
    const filters: HealthFilter[] = ['attention', ...presentKinds, 'all']

    return (
        <ToggleGroup
            variant="outline"
            size="sm"
            spacing={1}
            className="flex-wrap"
            aria-label="Filter models by health"
            value={[activeHealthFilter]}
            onValueChange={(next: string[]) => {
                const [picked] = next
                if (isHealthFilter(picked)) {
                    setHealthFilter(picked)
                }
            }}
        >
            {filters.map((filter) => (
                <ToggleGroupItem key={filter} value={filter} data-attr={`models-list-filter-${filter}`}>
                    {FILTER_LABELS[filter]}
                    <span translate="no" className="text-muted-foreground">
                        {healthCounts[filter]}
                    </span>
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}
