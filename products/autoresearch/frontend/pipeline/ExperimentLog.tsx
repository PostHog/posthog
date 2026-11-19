import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { type ExperimentLogFilter, ruledOut } from '../agentSearch'
import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { ExperimentLogEntry } from './ExperimentLogEntry'
import { SectionCard } from './SectionCard'
import { TrainingRunRow } from './TrainingRunRow'

const FILTER_OPTIONS: { value: ExperimentLogFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'kept', label: 'Improved' },
    { value: 'discarded', label: 'No gain' },
    { value: 'crashed', label: 'Crashed' },
]

/** Every run, newest first, with its experiments and the approaches it ruled out. Only the latest run shows its experiments by default. */
export function ExperimentLog(): JSX.Element {
    const { experimentLogGroups, experimentLogFilter, expandedLogRunIds } = useValues(autoresearchPipelineLogic)
    const { setExperimentLogFilter, toggleLogRun } = useActions(autoresearchPipelineLogic)
    return (
        <SectionCard
            title="Runs"
            actions={
                <LemonSegmentedButton
                    size="xsmall"
                    value={experimentLogFilter}
                    onChange={setExperimentLogFilter}
                    options={FILTER_OPTIONS}
                    data-attr="autoresearch-experiment-log-filter"
                />
            }
        >
            {experimentLogGroups.map((group, index) => {
                const showEntries = index === 0 || expandedLogRunIds.includes(group.run.id)
                const ruledOutLabels = showEntries ? ruledOut(group.run) : []
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
                        {ruledOutLabels.length > 0 && (
                            <div className="border-t px-3 py-2 flex flex-wrap items-center gap-1 text-xs">
                                <span className="text-muted">Ruled out:</span>
                                {ruledOutLabels.map((label, labelIndex) => (
                                    <LemonTag key={labelIndex} size="small">
                                        {label}
                                    </LemonTag>
                                ))}
                            </div>
                        )}
                    </TrainingRunRow>
                )
            })}
        </SectionCard>
    )
}
