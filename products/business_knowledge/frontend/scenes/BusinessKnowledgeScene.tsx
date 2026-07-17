import { useActions, useValues } from 'kea'

import { IconBook, IconCheck, IconPencil, IconPlusSmall, IconRefresh, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCollapse, LemonDialog, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { RefreshIntervalOption } from '../api'
import { CreateKnowledgeSourceModal } from '../components/CreateKnowledgeSourceModal'
import { EditKnowledgeSourceModal } from '../components/EditKnowledgeSourceModal'
import { RefreshStatusCell } from '../components/RefreshStatusCell'
import { StatusTag } from '../components/StatusTag'
import { type AggregatedGap, KnowledgeSource, businessKnowledgeLogic } from './businessKnowledgeLogic'

const REFRESH_INTERVAL_OPTIONS: RefreshIntervalOption[] = [
    { value: 'manual', label: 'Manual only' },
    { value: '1h', label: 'Every hour' },
    { value: '6h', label: 'Every 6 hours' },
    { value: '24h', label: 'Every day' },
    { value: '7d', label: 'Every week' },
]

export const scene: SceneExport = {
    component: BusinessKnowledgeScene,
    logic: businessKnowledgeLogic,
}

export function BusinessKnowledgeScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const { sources, sourcesLoading, readyCount, totalChunks, refreshingIds, gapSuggestions, gapSuggestionsLoading } =
        useValues(businessKnowledgeLogic)
    const { openCreateModal, openEditModal, deleteSource, refreshSource, acceptGapSuggestion, dismissGapSuggestion } =
        useActions(businessKnowledgeLogic)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text, public URLs, or files so PostHog AI can understand your business context, vision, and policies."
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBook /> }}
                actions={
                    <LemonButton type="primary" icon={<IconPlusSmall />} onClick={() => openCreateModal()}>
                        Add source
                    </LemonButton>
                }
            />

            <div className="flex gap-4 text-sm text-muted mb-2">
                <span>{readyCount} ready</span>
                <span>•</span>
                <span>{totalChunks.toLocaleString()} chunks indexed</span>
            </div>

            {gapSuggestions.length > 0 && (
                <GapSuggestionsPanel
                    suggestions={gapSuggestions}
                    loading={gapSuggestionsLoading}
                    onAccept={acceptGapSuggestion}
                    onDismiss={dismissGapSuggestion}
                />
            )}

            <LemonTable<KnowledgeSource>
                dataSource={sources}
                loading={sourcesLoading}
                rowKey={(row) => row.id}
                onRow={(row) => ({
                    onClick: () => openEditModal(row),
                    style: { cursor: 'pointer' },
                })}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, row) => (
                            <div className="flex flex-col">
                                <span className="flex items-center gap-1">
                                    <strong>{row.name}</strong>
                                    {row.has_unsafe_documents ? (
                                        <LemonTag
                                            type="danger"
                                            title="One or more documents were flagged unsafe by the content classifier and are excluded from agent search."
                                        >
                                            unsafe content
                                        </LemonTag>
                                    ) : null}
                                </span>
                                {row.source_type === 'url' && row.source_url ? (
                                    <Link
                                        to={row.source_url}
                                        target="_blank"
                                        className="text-xs text-muted truncate"
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        {row.source_url}
                                    </Link>
                                ) : row.source_type === 'file' && row.original_filename ? (
                                    <span className="text-xs text-muted truncate">{row.original_filename}</span>
                                ) : null}
                            </div>
                        ),
                    },
                    {
                        title: 'Type',
                        key: 'source_type',
                        render: (_, row) => <LemonTag>{row.source_type}</LemonTag>,
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, row) => <StatusTag source={row} />,
                    },
                    {
                        title: 'Pages / chunks',
                        key: 'chunk_count',
                        render: (_, row) => {
                            const pages = row.document_count
                            return row.source_type === 'url' && row.crawl_mode && row.crawl_mode !== 'single'
                                ? `${pages.toLocaleString()} / ${row.chunk_count.toLocaleString()}`
                                : row.chunk_count.toLocaleString()
                        },
                    },
                    {
                        title: 'Added',
                        key: 'created_at',
                        render: (_, row) => <TZLabel time={row.created_at} />,
                    },
                    {
                        title: 'Last refresh',
                        key: 'last_refresh_at',
                        render: (_, row) => <RefreshStatusCell source={row} />,
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 0,
                        render: (_, row) => (
                            <div className="flex gap-1 justify-end">
                                {row.source_type === 'url' && (
                                    <LemonButton
                                        icon={<IconRefresh />}
                                        size="small"
                                        tooltip="Re-fetch and re-index this URL"
                                        loading={refreshingIds.includes(row.id)}
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            refreshSource(row.id)
                                        }}
                                    />
                                )}
                                <LemonButton
                                    icon={<IconPencil />}
                                    size="small"
                                    tooltip="Edit"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        openEditModal(row)
                                    }}
                                />
                                <LemonButton
                                    icon={<IconTrash />}
                                    status="danger"
                                    size="small"
                                    tooltip="Delete"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        LemonDialog.open({
                                            title: `Delete "${row.name}"?`,
                                            description: 'Chunks will be removed.',
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => deleteSource(row.id),
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }}
                                />
                            </div>
                        ),
                    },
                ]}
                emptyState="No knowledge sources yet. Click 'Add source' to index your first."
            />

            <CreateKnowledgeSourceModal refreshIntervalOptions={REFRESH_INTERVAL_OPTIONS} />
            <EditKnowledgeSourceModal refreshIntervalOptions={REFRESH_INTERVAL_OPTIONS} />
        </SceneContent>
    )
}

function GapSuggestionsPanel({
    suggestions,
    loading,
    onAccept,
    onDismiss,
}: {
    suggestions: AggregatedGap[]
    loading: boolean
    onAccept: (normalizedTopic: string, topic: string) => void
    onDismiss: (normalizedTopic: string) => void
}): JSX.Element {
    return (
        <LemonCollapse
            className="mb-4"
            panels={[
                {
                    key: 'gap_suggestions',
                    header: (
                        <span className="flex items-center gap-1">
                            Suggested additions
                            <LemonTag type="highlight" size="small">
                                {suggestions.length}
                            </LemonTag>
                        </span>
                    ),
                    content: loading ? (
                        <div className="text-muted text-sm p-2">Loading suggestions...</div>
                    ) : (
                        <div className="space-y-2">
                            <p className="text-muted text-xs">
                                Topics customers asked about that the AI couldn't answer from your knowledge base.
                                Accept to create a source, or dismiss.
                            </p>
                            {suggestions.map((gap) => (
                                <LemonCard key={gap.normalized_topic} className="flex items-center justify-between p-3">
                                    <div className="flex-1 min-w-0">
                                        <div className="font-medium truncate">{gap.topic}</div>
                                        <div className="text-xs text-muted">
                                            {gap.ticket_count} ticket{gap.ticket_count !== 1 ? 's' : ''}
                                        </div>
                                    </div>
                                    <div className="flex gap-1 ml-2">
                                        <LemonButton
                                            size="small"
                                            type="primary"
                                            icon={<IconCheck />}
                                            tooltip="Accept — create a source for this topic"
                                            onClick={() => onAccept(gap.normalized_topic, gap.topic)}
                                        >
                                            Accept
                                        </LemonButton>
                                        <LemonButton
                                            size="small"
                                            icon={<IconX />}
                                            tooltip="Dismiss"
                                            onClick={() => onDismiss(gap.normalized_topic)}
                                        />
                                    </div>
                                </LemonCard>
                            ))}
                        </div>
                    ),
                },
            ]}
        />
    )
}
