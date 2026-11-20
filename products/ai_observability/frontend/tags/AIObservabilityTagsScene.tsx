import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconSearch } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonSkeleton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import 'lib/components/Cards/InsightCard/InsightCard.scss'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'

import type { TaggerApi } from '../generated/api.schemas'
import { llmTaggersLogic } from './llmTaggersLogic'
import { TaggersDeprecationBanner } from './TaggersDeprecationBanner'

export const scene: SceneExport = {
    component: AIObservabilityTagsScene,
    productKey: ProductKey.AI_OBSERVABILITY,
}

function TaggerMetrics(): JSX.Element {
    const { chartQuery, totalRuns, taggers, runStatsLoading } = useValues(llmTaggersLogic)

    if (runStatsLoading) {
        return <LemonSkeleton className="h-80 w-full mb-6" />
    }

    return (
        <div className="mb-6">
            <div className="flex gap-4 h-80">
                {chartQuery ? (
                    <div className="flex-[2] bg-bg-light rounded p-4 flex flex-col InsightCard h-full">
                        <h3 className="text-lg font-semibold mb-1">Tags over time</h3>
                        <p className="text-muted text-sm mb-3">Tag counts broken down by tagger and tag name</p>
                        <div className="flex-1 flex flex-col min-h-0">
                            <Query
                                query={{ kind: NodeKind.InsightVizNode, source: chartQuery } as InsightVizNode}
                                readOnly
                                embedded
                                inSharedMode
                                context={{
                                    insightProps: {
                                        dashboardItemId: 'new-tagger-metrics-chart',
                                        dataNodeCollectionId: 'tagger-metrics',
                                    },
                                }}
                            />
                        </div>
                    </div>
                ) : (
                    <div className="flex-[2] bg-bg-light border rounded p-8 flex items-center justify-center">
                        <div className="text-muted text-center">No taggers to display.</div>
                    </div>
                )}

                <div className="flex-1 grid grid-cols-1 gap-4">
                    <div className="bg-bg-light border rounded p-4 flex flex-col">
                        <div className="text-muted text-xs font-medium uppercase mb-2">Taggers</div>
                        <div className="text-3xl font-semibold">{taggers.length}</div>
                    </div>
                    <div className="bg-bg-light border rounded p-4 flex flex-col">
                        <div className="text-muted text-xs font-medium uppercase mb-2">Total runs</div>
                        <div className="text-3xl font-semibold">{totalRuns}</div>
                        {totalRuns === 0 && <div className="text-muted text-sm mt-1">No activity</div>}
                    </div>
                </div>
            </div>
        </div>
    )
}

function AIObservabilityTagsContent(): JSX.Element {
    const taggersLogic = llmTaggersLogic()
    const {
        filteredTaggers,
        taggersLoading,
        taggersFilter,
        dateFilter,
        runStatsMap,
        tagDistributionMap,
        someTaggersMigrated,
    } = useValues(taggersLogic)
    const { setTaggersFilter, setDates } = useActions(taggersLogic)
    const { searchParams } = useValues(router)
    const taggerUrl = (id: string): string => combineUrl(urls.aiObservabilityTag(id), searchParams).url

    const columns: LemonTableColumns<TaggerApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, tagger) => (
                <div className="flex flex-col">
                    <Link to={taggerUrl(tagger.id)} className="font-semibold text-primary">
                        {tagger.name}
                    </Link>
                    {tagger.description && <div className="text-muted text-sm">{tagger.description}</div>}
                </div>
            ),
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Status',
            key: 'enabled',
            render: (_, tagger) => {
                if (tagger.migrated_to_evaluation_id) {
                    return (
                        <Link
                            to={urls.aiObservabilityEvaluation(tagger.migrated_to_evaluation_id)}
                            data-attr="tagger-status-moved-to-evaluation"
                        >
                            Moved to evaluation
                        </Link>
                    )
                }
                return (
                    <span className={tagger.enabled ? 'text-success' : 'text-muted'}>
                        {tagger.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                )
            },
            sorter: (a, b) => Number(b.enabled) - Number(a.enabled),
        },
        {
            title: 'Runs',
            key: 'runs',
            render: (_, tagger) => {
                const count = runStatsMap[tagger.id] ?? 0
                return <span className={count > 0 ? 'font-medium' : 'text-muted'}>{count}</span>
            },
            sorter: (a, b) => (runStatsMap[a.id] ?? 0) - (runStatsMap[b.id] ?? 0),
        },
        {
            title: 'Tags',
            key: 'tags',
            render: (_, tagger) => {
                const dist = tagDistributionMap[tagger.id]
                if (dist && dist.length > 0) {
                    return (
                        <div className="flex flex-wrap gap-1">
                            {dist.slice(0, 5).map((t) => (
                                <LemonTag key={t.name} type="option">
                                    {t.name} ({t.percent}%)
                                </LemonTag>
                            ))}
                            {dist.length > 5 && <LemonTag type="muted">+{dist.length - 5}</LemonTag>}
                        </div>
                    )
                }
                return <span className="text-muted italic">No data</span>
            },
        },
        {
            title: 'Method',
            key: 'method',
            render: (_, tagger) => (
                <LemonTag type={tagger.tagger_type === 'hog' ? 'option' : 'caution'}>
                    {tagger.tagger_type === 'hog' ? 'Hog' : 'LLM'}
                </LemonTag>
            ),
        },
        {
            title: 'Config',
            key: 'config',
            render: (_, tagger) => {
                const preview =
                    tagger.tagger_type === 'hog'
                        ? 'source' in tagger.tagger_config
                            ? tagger.tagger_config.source
                            : ''
                        : 'prompt' in tagger.tagger_config
                          ? tagger.tagger_config.prompt
                          : ''
                return (
                    <Tooltip title={preview} placement="top">
                        <div className="max-w-md">
                            <div className="text-sm font-mono bg-bg-light border rounded px-2 py-1 truncate cursor-default">
                                {preview || '(empty)'}
                            </div>
                        </div>
                    </Tooltip>
                )
            },
        },
    ]

    return (
        <div className="space-y-4">
            <TaggersDeprecationBanner someMigrated={someTaggersMigrated} />
            <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />

            <TaggerMetrics />

            <div className="flex items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search taggers..."
                    value={taggersFilter}
                    onChange={setTaggersFilter}
                    prefix={<IconSearch />}
                    className="max-w-sm"
                />
            </div>

            <LemonTable
                columns={columns}
                dataSource={filteredTaggers}
                loading={taggersLoading}
                rowKey="id"
                pagination={{
                    pageSize: 50,
                }}
                nouns={['tagger', 'taggers']}
                emptyState={<div className="text-center p-8 text-muted">No taggers found.</div>}
            />
        </div>
    )
}

export function AIObservabilityTagsScene(): JSX.Element {
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)

    if (!receivedFeatureFlags) {
        return (
            <SceneContent>
                <LemonSkeleton className="w-full h-96" />
            </SceneContent>
        )
    }

    if (!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TAGS]) {
        return (
            <SceneContent>
                <LemonBanner type="warning">Taggers are not enabled for this project.</LemonBanner>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Taggers"
                description="Tags that taggers added to your AI generations."
                resourceType={{ type: 'llm_tags' }}
            />
            <AIObservabilityTagsContent />
        </SceneContent>
    )
}
