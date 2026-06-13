import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconPlus, IconSearch, IconTrash, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { getUnhealthyProviderKey, providerKeyStateIssueDescription } from '../settings/providerKeyStateUtils'
import { TrialUsageMeter } from '../settings/TrialUsageMeter'
import { llmTaggersLogic } from './llmTaggersLogic'
import { Tagger } from './types'

export const scene: SceneExport = {
    component: AIObservabilityTagsScene,
    logic: llmTaggersLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
}

function TaggerMetrics(): JSX.Element {
    const { chartQuery, totalRuns, taggers, runStatsLoading } = useValues(llmTaggersLogic)

    const enabledCount = taggers.filter((t) => t.enabled && !t.deleted).length

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
                        <div className="text-muted text-center">
                            No enabled taggers to display. Create and enable taggers to see metrics.
                        </div>
                    </div>
                )}

                <div className="flex-1 grid grid-cols-1 gap-4">
                    <div className="bg-bg-light border rounded p-4 flex flex-col">
                        <div className="text-muted text-xs font-medium uppercase mb-2">Enabled taggers</div>
                        <div className="text-3xl font-semibold">{enabledCount}</div>
                        <div className="text-muted text-sm mt-1">{taggers.length} total</div>
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

function getTaggerProviderKeyIssue(tagger: Tagger, providerKeys: LLMProviderKey[]): LLMProviderKey | null {
    if (tagger.tagger_type === 'hog') {
        return null
    }

    return getUnhealthyProviderKey(providerKeys, tagger.model_configuration?.provider_key_id)
}

function AIObservabilityTagsContent(): JSX.Element {
    const taggersLogic = llmTaggersLogic()
    const { filteredTaggers, taggersLoading, taggersFilter, dateFilter, runStatsMap, tagDistributionMap } =
        useValues(taggersLogic)
    const { providerKeys } = useValues(llmProviderKeysLogic)
    const { setTaggersFilter, toggleTaggerEnabled, loadTaggers, setDates } = useActions(taggersLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const taggerUrl = (id: string): string => combineUrl(urls.aiObservabilityTag(id), searchParams).url

    const columns: LemonTableColumns<Tagger> = [
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
                const providerKeyIssue = tagger.enabled ? getTaggerProviderKeyIssue(tagger, providerKeys) : null
                if (providerKeyIssue) {
                    return (
                        <Tooltip
                            title={`Paused because API key ${providerKeyIssue.name} ${providerKeyStateIssueDescription(
                                providerKeyIssue.state
                            )}.`}
                        >
                            <LemonTag type="warning" icon={<IconWarning />} data-attr="tagger-status-key-issue">
                                Key issue
                            </LemonTag>
                        </Tooltip>
                    )
                }

                return (
                    <div className="flex items-center gap-2">
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonSwitch
                                checked={tagger.enabled}
                                onChange={() => toggleTaggerEnabled(tagger.id)}
                                size="small"
                                data-attr="toggle-tagger-enabled"
                            />
                        </AccessControlAction>
                        <span className={tagger.enabled ? 'text-success' : 'text-muted'}>
                            {tagger.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                    </div>
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
        {
            title: 'Actions',
            key: 'actions',
            render: (_, tagger) => (
                <div className="flex gap-1">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPencil />}
                            onClick={() =>
                                push(
                                    combineUrl(urls.aiObservabilityTag(tagger.id), {
                                        ...searchParams,
                                        tab: 'configuration',
                                    }).url
                                )
                            }
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={() => {
                                deleteWithUndo({
                                    endpoint: `environments/${currentTeamId}/taggers`,
                                    object: tagger,
                                    callback: () => loadTaggers(),
                                })
                            }}
                        />
                    </AccessControlAction>
                </div>
            ),
        },
    ]

    return (
        <div className="space-y-4">
            <TrialUsageMeter showSettingsLink={false} noun="runs" />

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
    const { searchParams } = useValues(router)
    return (
        <SceneContent>
            <SceneTitleSection
                name="Tags"
                description="Set up taggers to automatically add custom tags to your AI generations."
                resourceType={{ type: 'llm_tags' }}
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            to={combineUrl(urls.aiObservabilityTag('new'), searchParams).url}
                            data-attr="create-tagger-button"
                        >
                            Create tagger
                        </LemonButton>
                    </AccessControlAction>
                }
            />
            <AIObservabilityTagsContent />
        </SceneContent>
    )
}
