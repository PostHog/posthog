import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import type { ExperimentLogFilter } from '../agentSearch'
import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { ExperimentLogEntry } from './ExperimentLogEntry'
import { TrainingRunRow } from './TrainingRunRow'

const FILTER_OPTIONS: { value: ExperimentLogFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'kept', label: 'Kept' },
    { value: 'discarded', label: 'Discarded' },
    { value: 'crashed', label: 'Crashed' },
]

/** Every experiment, grouped by training run, newest first. Only the latest run shows its experiments by default. */
export function ExperimentLog(): JSX.Element {
    const { experimentLogGroups, experimentLogFilter, expandedLogRunIds } = useValues(autoresearchPipelineLogic)
    const { setExperimentLogFilter, toggleLogRun } = useActions(autoresearchPipelineLogic)
    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="text-sm font-semibold">Experiment log</div>
                <LemonSegmentedButton
                    size="xsmall"
                    value={experimentLogFilter}
                    onChange={setExperimentLogFilter}
                    options={FILTER_OPTIONS}
                    data-attr="autoresearch-experiment-log-filter"
                />
            </div>
            {experimentLogGroups.map((group, index) => {
                const showEntries = index === 0 || expandedLogRunIds.includes(group.run.id)
                return (
                    <TrainingRunRow key={group.run.id} run={group.run} runNumber={group.runNumber}>
                        {group.entries.length === 0 ? (
                            group.run.iterations.length > 0 && (
                                <div className="border-t px-3 py-2 text-xs text-muted">
                                    No experiments match this filter.
                                </div>
                            )
                        ) : showEntries ? (
                            <div className="border-t">
                                {group.entries.map((entry) => (
                                    <ExperimentLogEntry key={entry.seq} entry={entry} />
                                ))}
                            </div>
                        ) : (
                            <div className="border-t px-1 py-1">
                                <LemonButton
                                    size="small"
                                    onClick={() => toggleLogRun(group.run.id)}
                                    data-attr="autoresearch-experiment-log-show-run"
                                >
                                    {`Show ${group.entries.length} earlier ${group.entries.length === 1 ? 'experiment' : 'experiments'}`}
                                </LemonButton>
                            </div>
                        )}
                    </TrainingRunRow>
                )
            })}
        </div>
    )
}
