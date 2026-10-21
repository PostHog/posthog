import { useActions } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { type SearchPoint, formatDelta } from '../agentSearch'
import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { EXPERIMENT_STATUS } from './experimentStatus'

/** One experiment in the log as one line. Click it to open the experiment. */
export function ExperimentLogEntry({ entry }: { entry: SearchPoint }): JSX.Element {
    const { openExperiment } = useActions(autoresearchPipelineLogic)
    const status = EXPERIMENT_STATUS[entry.status]
    const delta = formatDelta(entry.delta)
    return (
        <div className="border-t first:border-t-0 px-1 py-0.5">
            <LemonButton
                fullWidth
                size="small"
                onClick={() => openExperiment(entry, 'log')}
                data-attr="autoresearch-experiment-log-entry"
                tooltip={`${status.label}. Open the experiment.`}
            >
                <span className="flex items-center gap-2 min-w-0 w-full font-normal">
                    <span className={`size-2 rounded-full shrink-0 ${status.dotClassName}`} aria-label={status.label} />
                    <span className="text-xs text-muted tabular-nums shrink-0">#{entry.iterationNumber}</span>
                    <span className="text-sm truncate flex-1 min-w-0">{entry.summary || 'No description'}</span>
                    {entry.isLiveModel && (
                        <LemonTag type="completion" size="small" className="shrink-0">
                            Live model
                        </LemonTag>
                    )}
                    {entry.isScoredAlongside && (
                        <LemonTag type="highlight" size="small" className="shrink-0">
                            Scored alongside
                        </LemonTag>
                    )}
                    {delta && (
                        <span
                            className={`text-xs tabular-nums shrink-0 ${
                                entry.delta != null && entry.delta > 0 ? 'text-success' : 'text-muted'
                            }`}
                        >
                            {delta}
                        </span>
                    )}
                    <span className="text-xs font-semibold tabular-nums shrink-0 w-10 text-right">
                        {entry.holdoutScore != null ? entry.holdoutScore.toFixed(3) : '—'}
                    </span>
                </span>
            </LemonButton>
        </div>
    )
}
