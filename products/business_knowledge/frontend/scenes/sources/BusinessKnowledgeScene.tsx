import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus, IconPlusSmall, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BusinessKnowledgeTabs } from '../../components/BusinessKnowledgeTabs/BusinessKnowledgeTabs'
import { CreateKnowledgeSourceModal } from '../../components/CreateKnowledgeSourceModal/CreateKnowledgeSourceModal'
import { StatusTag } from '../../components/StatusTag/StatusTag'
import { businessKnowledgeEmptyState } from '../../emptyState/businessKnowledgeEmptyState'
import {
    KnowledgeSource,
    REFRESH_INTERVAL_OPTIONS,
    LIBRARY_SCOPE_ALL,
    LIBRARY_SCOPE_UNFILED,
    businessKnowledgeLogic,
} from './businessKnowledgeLogic'
import { KnowledgeSourceNameCell } from './KnowledgeSourceNameCell'
import { LibraryDialog } from './LibraryDialog'
import { LibraryRow } from './LibraryRow'
import { LibrarySummary } from './LibrarySummary'
import { RefreshStatusCell } from './RefreshStatusCell'
import { SourceLibrariesCell } from './SourceLibrariesCell'

export const scene: SceneExport = {
    component: BusinessKnowledgeScene,
    logic: businessKnowledgeLogic,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
    emptyState: businessKnowledgeEmptyState,
}

export function BusinessKnowledgeScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const {
        sources,
        sourcesLoading,
        readyCount,
        totalChunks,
        refreshingIds,
        searchTerm,
        sourceTypeFilter,
        addedByFilter,
        libraryScope,
        selectedLibrary,
    } = useValues(businessKnowledgeLogic)
    const { openCreateModal, deleteSource, refreshSource, setSearchTerm, setSourceTypeFilter, setAddedByFilter } =
        useActions(businessKnowledgeLogic)
    const { push } = useActions(router)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text, public URLs, or files so PostHog AI can understand your business context, vision, and policies."
                resourceType={{ type: 'business_knowledge' }}
                actions={
                    todayRailNav ? (
                        <Button variant="primary" onClick={() => openCreateModal()}>
                            <IconPlus />
                            Add source
                        </Button>
                    ) : (
                        <LemonButton type="primary" icon={<IconPlusSmall />} onClick={() => openCreateModal()}>
                            Add source
                        </LemonButton>
                    )
                }
            />
            <BusinessKnowledgeTabs activeTab="sources" />
            <SceneSection title="Libraries" className="gap-y-2">
                <LibraryRow />
                <LibrarySummary />
            </SceneSection>
            <SceneDivider />
            <SceneSection
                title={
                    selectedLibrary
                        ? `Sources in ${selectedLibrary.name}`
                        : libraryScope === LIBRARY_SCOPE_UNFILED
                          ? 'Sources with no library'
                          : 'Sources'
                }
                description={`${readyCount} ready · ${pluralize(totalChunks, 'chunk')} indexed`}
                className="gap-y-2"
            >
                <div className="flex flex-wrap gap-2 items-center">
                    <LemonInput
                        type="search"
                        placeholder="Search by name or URL"
                        value={searchTerm}
                        onChange={setSearchTerm}
                        className="max-w-80"
                    />
                    <LemonSelect
                        value={sourceTypeFilter}
                        onChange={setSourceTypeFilter}
                        options={[
                            { value: 'all', label: 'All types' },
                            { value: 'text', label: 'Text' },
                            { value: 'url', label: 'URL' },
                            { value: 'file', label: 'File' },
                        ]}
                    />
                    <LemonSelect
                        value={addedByFilter}
                        onChange={setAddedByFilter}
                        options={[
                            { value: 'all', label: 'All sources' },
                            { value: 'human', label: 'Human' },
                            { value: 'learned', label: 'Learned' },
                        ]}
                        data-attr="business-knowledge-added-by-filter"
                    />
                </div>

                <LemonTable<KnowledgeSource>
                    dataSource={sources}
                    loading={sourcesLoading}
                    pagination={{ pageSize: 20 }}
                    rowKey={(row) => row.id}
                    onRow={(row) => {
                        const sourceUrl = urls.businessKnowledgeSource(row.id)
                        return {
                            style: { cursor: 'pointer' },
                            onClick: (e: React.MouseEvent) => {
                                if (e.metaKey || e.ctrlKey) {
                                    e.preventDefault()
                                    e.stopPropagation()
                                    newInternalTab(sourceUrl)
                                } else {
                                    push(sourceUrl)
                                }
                            },
                            onAuxClick: (e: React.MouseEvent) => {
                                if (e.button === 1) {
                                    e.preventDefault()
                                    e.stopPropagation()
                                    newInternalTab(sourceUrl)
                                }
                            },
                        }
                    }}
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, row) => <KnowledgeSourceNameCell source={row} />,
                        },
                        {
                            title: 'Type',
                            key: 'source_type',
                            render: (_, row) => <LemonTag>{row.source_type}</LemonTag>,
                        },
                        {
                            title: 'Libraries',
                            key: 'library_ids',
                            render: (_, row) => <SourceLibrariesCell source={row} />,
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
                                    {row.source_type === 'url' && !row.is_generated && (
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
                    emptyState={
                        searchTerm || sourceTypeFilter !== 'all' || addedByFilter !== 'all' ? (
                            'No sources match your search or filter.'
                        ) : libraryScope === LIBRARY_SCOPE_UNFILED ? (
                            'Every source is in a library.'
                        ) : libraryScope !== LIBRARY_SCOPE_ALL ? (
                            <div className="flex flex-col items-center gap-2 py-4">
                                <span>{selectedLibrary?.name ?? 'This library'} has no sources yet.</span>
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    icon={<IconPlusSmall />}
                                    onClick={() => openCreateModal()}
                                >
                                    Add source
                                </LemonButton>
                            </div>
                        ) : (
                            "No knowledge sources yet. Click 'Add source' to index your first."
                        )
                    }
                />
            </SceneSection>

            <CreateKnowledgeSourceModal refreshIntervalOptions={REFRESH_INTERVAL_OPTIONS} />
            <LibraryDialog />
        </SceneContent>
    )
}
