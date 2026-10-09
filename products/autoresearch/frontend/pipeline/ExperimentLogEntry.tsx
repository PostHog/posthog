import { LemonTag } from '@posthog/lemon-ui'

import { type SearchPoint, formatDelta, formatModelSpec } from '../agentSearch'

const STATUS_TAG: Record<SearchPoint['status'], { type: 'success' | 'default' | 'danger'; label: string }> = {
    kept: { type: 'success', label: 'Kept' },
    discarded: { type: 'default', label: 'Discarded' },
    crashed: { type: 'danger', label: 'Crashed' },
}

/** One experiment in the log: its status, its change against the best score before it, and what the agent tried. */
export function ExperimentLogEntry({ entry }: { entry: SearchPoint }): JSX.Element {
    const tag = STATUS_TAG[entry.status]
    const spec = formatModelSpec(entry.modelSpec)
    const delta = formatDelta(entry.delta)
    return (
        <div className="border-t first:border-t-0 px-3 py-2 space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold">Experiment {entry.iterationNumber}</span>
                <LemonTag type={tag.type} size="small">
                    {tag.label}
                </LemonTag>
                {entry.isLiveModel && (
                    <LemonTag type="completion" size="small">
                        Live model
                    </LemonTag>
                )}
                <span className="text-xs text-muted tabular-nums ml-auto">
                    {entry.holdoutScore != null ? `AUC ${entry.holdoutScore.toFixed(3)}` : 'No score'}
                    {delta && (
                        <span className={entry.delta != null && entry.delta > 0 ? 'text-success ml-2' : 'ml-2'}>
                            {delta}
                        </span>
                    )}
                </span>
            </div>
            {entry.agentDescription && <div className="text-sm">{entry.agentDescription}</div>}
            {spec && (
                <div className="text-xs text-muted font-mono break-words">
                    {spec.className}
                    {spec.params && ` · ${spec.params}`}
                </div>
            )}
        </div>
    )
}
