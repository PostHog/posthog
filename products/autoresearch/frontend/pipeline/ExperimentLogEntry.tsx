import { useActions } from 'kea'

import { LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { type SearchPoint, formatDelta, formatModelSpec } from '../agentSearch'
import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'

const STATUS_TAG: Record<SearchPoint['status'], { type: 'success' | 'default' | 'danger'; label: string }> = {
    kept: { type: 'success', label: 'Kept' },
    discarded: { type: 'default', label: 'Discarded' },
    crashed: { type: 'danger', label: 'Crashed' },
}

/** One experiment in the log as one line, with the agent's own notes behind a toggle. */
export function ExperimentLogEntry({
    entry,
    defaultOpen = false,
}: {
    entry: SearchPoint
    defaultOpen?: boolean
}): JSX.Element {
    const { experimentDetailsOpened } = useActions(autoresearchPipelineLogic)
    const tag = STATUS_TAG[entry.status]
    const spec = formatModelSpec(entry.modelSpec)
    const delta = formatDelta(entry.delta)
    const hasNotes = (!!entry.agentDescription && entry.agentDescription !== entry.summary) || !!spec
    return (
        <div className="border-t first:border-t-0 px-3 py-2 space-y-1">
            <div className="flex items-center gap-2 min-w-0">
                <span className="text-sm font-semibold shrink-0">#{entry.iterationNumber}</span>
                <LemonTag type={tag.type} size="small" className="shrink-0">
                    {tag.label}
                </LemonTag>
                {entry.isLiveModel && (
                    <LemonTag type="completion" size="small" className="shrink-0">
                        Live model
                    </LemonTag>
                )}
                <span className="text-sm truncate flex-1 min-w-0" title={entry.summary}>
                    {entry.summary}
                </span>
                <span className="text-xs text-muted tabular-nums shrink-0">
                    {entry.holdoutScore != null ? `AUC ${entry.holdoutScore.toFixed(3)}` : 'No score'}
                    {delta && (
                        <span className={entry.delta != null && entry.delta > 0 ? 'text-success ml-2' : 'ml-2'}>
                            {delta}
                        </span>
                    )}
                </span>
            </div>
            {hasNotes && (
                <LemonCollapse
                    embedded
                    size="xsmall"
                    defaultActiveKey={defaultOpen ? 'notes' : undefined}
                    onChange={(key) => key === 'notes' && experimentDetailsOpened(entry)}
                    panels={[
                        {
                            key: 'notes',
                            header: "Agent's working notes",
                            dataAttr: 'autoresearch-experiment-details',
                            content: (
                                <div className="space-y-1">
                                    {entry.agentDescription && (
                                        <div className="text-sm whitespace-pre-line">{entry.agentDescription}</div>
                                    )}
                                    {spec && (
                                        <div className="text-xs text-muted font-mono break-words">
                                            {spec.className}
                                            {spec.params && ` · ${spec.params}`}
                                        </div>
                                    )}
                                </div>
                            ),
                        },
                    ]}
                />
            )}
        </div>
    )
}
