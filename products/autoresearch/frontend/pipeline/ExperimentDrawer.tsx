import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonModal, LemonTable, LemonTabs, LemonTag, Spinner } from '@posthog/lemon-ui'

import { formatDelta, modelSpecRows } from '../agentSearch'
import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { EXPERIMENT_STATUS } from './experimentStatus'

type DrawerTab = 'notes' | 'settings' | 'files'

/** One experiment in full: its plain line, status, score and change, then the agent's notes, model settings and run files. */
export function ExperimentDrawer(): JSX.Element {
    const { openedExperiment, artifactsByRun, artifactsByRunLoading } = useValues(autoresearchPipelineLogic)
    const { closeExperiment, viewArtifact } = useActions(autoresearchPipelineLogic)
    const [activeTab, setActiveTab] = useState<DrawerTab>('notes')
    const experiment = openedExperiment
    const status = experiment ? EXPERIMENT_STATUS[experiment.status] : null
    const delta = experiment ? formatDelta(experiment.delta) : null
    const settings = experiment ? modelSpecRows(experiment.modelSpec) : []
    const paths = experiment ? artifactsByRun[experiment.runId] : undefined

    return (
        <LemonModal
            isOpen={!!experiment}
            onClose={() => {
                closeExperiment()
                setActiveTab('notes')
            }}
            title={experiment ? `Run ${experiment.runNumber} · experiment #${experiment.iterationNumber}` : ''}
            width={720}
        >
            {experiment && status && (
                <div className="space-y-3" data-attr="autoresearch-experiment-drawer">
                    <div className="text-base font-semibold">{experiment.summary || 'No description'}</div>
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                        <LemonTag type={status.type}>{status.label}</LemonTag>
                        {experiment.isLiveModel && <LemonTag type="completion">Live model</LemonTag>}
                        {experiment.isScoredAlongside && <LemonTag type="highlight">Scored alongside</LemonTag>}
                        <span className="font-semibold tabular-nums">
                            {experiment.holdoutScore != null ? experiment.holdoutScore.toFixed(3) : 'No score'}
                        </span>
                        {delta && (
                            <span className="text-secondary">
                                <span
                                    className={experiment.delta != null && experiment.delta > 0 ? 'text-success' : ''}
                                >
                                    {delta}
                                </span>{' '}
                                vs the last improvement in this run
                            </span>
                        )}
                    </div>
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={setActiveTab}
                        tabs={[
                            {
                                key: 'notes',
                                label: "Agent's notes",
                                content: experiment.agentDescription ? (
                                    <div className="text-sm whitespace-pre-line">{experiment.agentDescription}</div>
                                ) : (
                                    <div className="text-sm text-muted">
                                        The agent left no notes for this experiment.
                                    </div>
                                ),
                            },
                            {
                                key: 'settings',
                                label: 'Model settings',
                                content: (
                                    <LemonTable
                                        size="small"
                                        dataSource={settings}
                                        rowKey="key"
                                        emptyState="No model settings recorded."
                                        columns={[
                                            {
                                                title: 'Setting',
                                                dataIndex: 'key',
                                                render: (_, row) => <span className="font-mono">{row.key}</span>,
                                            },
                                            {
                                                title: 'Value',
                                                dataIndex: 'value',
                                                render: (_, row) => (
                                                    <span className="font-mono break-all">{row.value}</span>
                                                ),
                                            },
                                        ]}
                                    />
                                ),
                            },
                            {
                                key: 'files',
                                label: 'Files',
                                content:
                                    paths === undefined && artifactsByRunLoading ? (
                                        <Spinner />
                                    ) : paths && paths.length > 0 ? (
                                        <div className="space-y-2">
                                            <div className="text-xs text-muted">
                                                Files the agent uploaded for run {experiment.runNumber}.
                                            </div>
                                            <div className="flex flex-wrap gap-2">
                                                {paths.map((path) => (
                                                    <LemonButton
                                                        key={path}
                                                        type="secondary"
                                                        size="small"
                                                        onClick={() => viewArtifact({ runId: experiment.runId, path })}
                                                        data-attr="autoresearch-experiment-drawer-file"
                                                    >
                                                        {path}
                                                    </LemonButton>
                                                ))}
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="text-sm text-muted">No files uploaded for this run.</div>
                                    ),
                            },
                        ]}
                    />
                </div>
            )}
        </LemonModal>
    )
}
