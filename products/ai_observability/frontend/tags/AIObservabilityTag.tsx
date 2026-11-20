import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, LemonTabs, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import 'lib/components/Cards/InsightCard/InsightCard.scss'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

import { TagRun, llmTaggerLogic } from './llmTaggerLogic'
import { TaggerConfiguration } from './TaggerConfiguration'
import { TaggersDeprecationBanner } from './TaggersDeprecationBanner'

function TagRunsChart({ id }: { id: string }): JSX.Element | null {
    const { runsChartQuery } = useValues(llmTaggerLogic({ id }))

    if (!runsChartQuery) {
        return null
    }

    return (
        <div className="bg-bg-light rounded p-4 mb-4 h-72 flex flex-col InsightCard">
            <h3 className="text-base font-semibold mb-1">Tag distribution over time</h3>
            <div className="flex-1 flex flex-col min-h-0">
                <Query
                    query={{ kind: NodeKind.InsightVizNode, source: runsChartQuery } as InsightVizNode}
                    readOnly
                    embedded
                    inSharedMode
                    context={{
                        insightProps: {
                            dashboardItemId: `new-tagger-runs-chart-${id}`,
                            dataNodeCollectionId: `tagger-runs-${id}`,
                        },
                    }}
                />
            </div>
        </div>
    )
}

function TagRunsTable({ id }: { id: string }): JSX.Element {
    const { tagRuns, tagRunsLoading, dateFilter } = useValues(llmTaggerLogic({ id }))
    const { loadTagRuns, setDates } = useActions(llmTaggerLogic({ id }))

    const columns: LemonTableColumns<TagRun> = [
        {
            title: 'Timestamp',
            key: 'timestamp',
            render: (_, run) => <TZLabel time={run.timestamp} />,
            sorter: (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        },
        {
            title: 'Generation',
            key: 'generation',
            render: (_, run) =>
                run.trace_id && run.target_event_id ? (
                    <div className="font-mono text-sm">
                        <Link
                            to={urls.aiObservabilityTrace(run.trace_id, { event: run.target_event_id })}
                            className="text-primary"
                        >
                            {run.target_event_id.slice(0, 12)}...
                        </Link>
                    </div>
                ) : (
                    <span className="text-muted text-sm">-</span>
                ),
        },
        {
            title: 'Tags',
            key: 'tags',
            render: (_, run) => (
                <div className="flex flex-wrap gap-1">
                    {run.tags.length > 0 ? (
                        run.tags.map((tag: string) => (
                            <LemonTag key={tag} type="highlight">
                                {tag}
                            </LemonTag>
                        ))
                    ) : (
                        <span className="text-muted text-sm">No tags</span>
                    )}
                </div>
            ),
        },
        {
            title: 'Reasoning',
            key: 'reasoning',
            render: (_, run) =>
                run.reasoning ? (
                    <Tooltip title={run.reasoning} placement="top">
                        <div className="max-w-md text-sm truncate cursor-default">{run.reasoning}</div>
                    </Tooltip>
                ) : (
                    <span className="text-muted text-sm">-</span>
                ),
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <div className="flex items-center gap-3">
                    <p className="text-muted text-sm m-0">Tag runs for this tagger.</p>
                    <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                </div>
                <LemonButton type="secondary" size="small" onClick={loadTagRuns}>
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={tagRuns}
                loading={tagRunsLoading}
                rowKey="target_event_id"
                pagination={{ pageSize: 20 }}
                nouns={['run', 'runs']}
                emptyState={<div className="text-center py-8 text-muted">No tag runs in this date range.</div>}
            />
        </div>
    )
}

export function AIObservabilityTag({ id }: { id: string }): JSX.Element {
    const { tagger, taggerLoading, activeTab } = useValues(llmTaggerLogic({ id }))
    const { setActiveTab } = useActions(llmTaggerLogic({ id }))

    if (taggerLoading) {
        return (
            <SceneContent>
                <LemonSkeleton className="w-full h-96" />
            </SceneContent>
        )
    }

    if (!tagger) {
        return (
            <SceneContent>
                <NotFound object="tagger" />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <TaggersDeprecationBanner migratedToEvaluationId={tagger.migrated_to_evaluation_id} />
            <div className="space-y-6">
                <div className="flex justify-between items-start pb-4 border-b">
                    <div className="space-y-2">
                        <h1 className="text-2xl font-semibold">{tagger.name}</h1>
                        <LemonTag type={tagger.enabled ? 'success' : 'default'}>
                            {tagger.enabled ? 'Enabled' : 'Disabled'}
                        </LemonTag>
                    </div>
                    <LemonButton type="secondary" icon={<IconArrowLeft />} to={urls.aiObservabilityTags()}>
                        Back
                    </LemonButton>
                </div>

                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as 'runs' | 'configuration')}
                    data-attr="llma-tagger-tabs"
                    tabs={[
                        {
                            key: 'runs',
                            label: 'Runs',
                            content: (
                                <div className="max-w-6xl">
                                    <TagRunsChart id={id} />
                                    <TagRunsTable id={id} />
                                </div>
                            ),
                        },
                        {
                            key: 'configuration',
                            label: 'Configuration',
                            content: <TaggerConfiguration tagger={tagger} />,
                        },
                    ]}
                />
            </div>
        </SceneContent>
    )
}
