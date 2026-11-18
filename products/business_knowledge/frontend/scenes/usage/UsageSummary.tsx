import { pluralize } from 'lib/utils/strings'

import type { KnowledgeUsageApi } from '../../generated/api.schemas'
import { UsageStat } from './UsageStat'

export function UsageSummary({ usage }: { usage: KnowledgeUsageApi }): JSX.Element {
    return (
        <div className="grid grid-cols-1 gap-2 @min-[48rem]/main-content:grid-cols-3">
            <UsageStat
                label="Agent runs that cited knowledge"
                value={usage.cited_run_count.toLocaleString()}
                caption={`In the last ${pluralize(usage.days, 'day')}`}
            />
            <UsageStat
                label="Cited knowledge learned from tickets"
                value={usage.learned_cited_run_count.toLocaleString()}
                caption={`Of ${pluralize(usage.cited_run_count, 'agent run')}`}
            />
            <UsageStat
                label="Sources cited"
                value={usage.cited_source_count.toLocaleString()}
                caption={`Of ${pluralize(usage.source_count, 'source')}`}
            />
        </div>
    )
}
