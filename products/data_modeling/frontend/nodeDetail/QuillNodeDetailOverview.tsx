import { NodeDetailOverview, type NodeDetailOverviewSummaries } from './NodeDetailOverview'
import type { ModelMetadataFacts } from './nodeDetailSceneLogic'
import { QuillModelHealthSummary } from './QuillModelHealthSummary'
import { QuillModelMetadata } from './QuillModelMetadata'
import { QuillModelTableSummary } from './QuillModelTableSummary'
import { QuillModelViewSummary } from './QuillModelViewSummary'

const QUILL_SUMMARIES: NodeDetailOverviewSummaries = {
    TableSummary: QuillModelTableSummary,
    ViewSummary: QuillModelViewSummary,
    HealthSummary: QuillModelHealthSummary,
}

export function QuillNodeDetailOverview({
    id,
    metadata,
}: {
    id: string
    metadata: ModelMetadataFacts | null
}): JSX.Element {
    return (
        <NodeDetailOverview
            id={id}
            metadata={metadata && <QuillModelMetadata {...metadata} />}
            summaries={QUILL_SUMMARIES}
        />
    )
}
