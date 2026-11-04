import { useActions, useValues } from 'kea'

import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { AttentionFilter, modelsOverviewLogic } from './modelsOverviewLogic'
import { ISSUE_LABELS, IssueKind } from './overviewIssueCopy'

const ISSUE_KIND_ORDER: IssueKind[] = ['suspended', 'failed', 'behind', 'checks']
const FILTER_LABELS: Record<AttentionFilter, string> = { all: 'All', ...ISSUE_LABELS }

function isAttentionFilter(value: string | undefined): value is AttentionFilter {
    return value !== undefined && value in FILTER_LABELS
}

export function ModelsOverviewAttentionFilter(): JSX.Element | null {
    const { attentionCounts, activeAttentionFilter } = useValues(modelsOverviewLogic)
    const { setAttentionFilter } = useActions(modelsOverviewLogic)
    const presentKinds = ISSUE_KIND_ORDER.filter((kind) => attentionCounts[kind] > 0)

    if (presentKinds.length < 2) {
        return null
    }

    return (
        <ToggleGroup
            variant="outline"
            size="sm"
            spacing={1}
            className="flex-wrap"
            aria-label="Show problems"
            value={[activeAttentionFilter]}
            onValueChange={(next: string[]) => {
                const [picked] = next
                if (isAttentionFilter(picked)) {
                    setAttentionFilter(picked)
                }
            }}
        >
            {(['all', ...presentKinds] as AttentionFilter[]).map((filter) => (
                <ToggleGroupItem key={filter} value={filter} data-attr={`models-overview-filter-${filter}`}>
                    {FILTER_LABELS[filter]}
                    <span translate="no" className="text-muted-foreground">
                        {attentionCounts[filter]}
                    </span>
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}
