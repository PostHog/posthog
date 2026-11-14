import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { KnowledgeSource } from './businessKnowledgeLogic'

export function SourceUsageCell({ source }: { source: KnowledgeSource }): JSX.Element {
    if (!source.cited_run_count || !source.last_cited_at) {
        return <span className="text-muted">Not cited yet</span>
    }
    return (
        <div className="flex flex-col gap-0.5">
            <span>{pluralize(source.cited_run_count, 'agent run')}</span>
            <span className="text-xs text-muted">
                last <TZLabel time={source.last_cited_at} />
            </span>
        </div>
    )
}
