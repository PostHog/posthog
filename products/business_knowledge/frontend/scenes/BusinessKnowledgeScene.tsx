import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconBook, IconPencil, IconPlusSmall, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CreateTab, KnowledgeSource, businessKnowledgeLogic } from './businessKnowledgeLogic'

export const scene: SceneExport = {
    component: BusinessKnowledgeScene,
    logic: businessKnowledgeLogic,
}

function StatusTag({ status }: { status: KnowledgeSource['status'] }): JSX.Element {
    const variant =
        status === 'ready' ? 'success' : status === 'error' ? 'danger' : status === 'processing' ? 'warning' : 'muted'
    return <LemonTag type={variant}>{status}</LemonTag>
}

function RefreshStatusCell({ source }: { source: KnowledgeSource }): JSX.Element | null {
    if (source.source_type !== 'url') {
        return null
    }
    if (!source.last_refresh_at) {
        return <span className="text-muted">—</span>
    }
    return (
        <div>
            <TZLabel time={source.last_refresh_at} />
            {source.last_refresh_status === 'error' ? (
                <LemonTag type="danger" title={source.last_refresh_error || undefined}>
                    refresh failed
                </LemonTag>
            ) : null}
        </div>
    )
}

export function BusinessKnowledgeScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const {
        sources,
        sourcesLoading,
        isCreateModalOpen,
        isEditModalOpen,
        createTab,
        editingSource,
        editingSourceTextLoading,
        readyCount,
        totalChunks,
        isTextSourceSubmitting,
        isUrlSourceSubmitting,
        isEditSourceSubmitting,
        refreshingIds,
    } = useValues(businessKnowledgeLogic)
    const {
        openCreateModal,
        closeCreateModal,
        setCreateTab,
        openEditModal,
        closeEditModal,
        deleteSource,
        refreshSource,
        submitTextSource,
        submitUrlSource,
        submitEditSource,
    } = useActions(businessKnowledgeLogic)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text or public URLs your AI support agent can cite when answering customer tickets."
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBook /> }}
                actions={
                    <LemonButton type="primary" icon={<IconPlusSmall />} onClick={openCreateModal}>
                        Add source
                    </LemonButton>
                }
            />

            <div className="flex gap-4 text-sm text-muted mb-2">
                <span>{readyCount} ready</span>
                <span>•</span>
                <span>{totalChunks.toLocaleString()} chunks indexed</span>
            </div>

            <LemonTable
                dataSource={sources}
                loading={sourcesLoading}
                rowKey={(row) => row.id}
                onRow={(row) => ({
                    onClick: () => (row.source_type === 'text' ? openEditModal(row) : undefined),
                    style: row.source_type === 'text' ? { cursor: 'pointer' } : undefined,
                })}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, row) => (
                            <div className="flex flex-col">
                                <strong>{row.name}</strong>
                                {row.source_type === 'url' && row.source_url ? (
                                    <Link to={row.source_url} target="_blank" className="text-xs text-muted truncate">
                                        {row.source_url}
                                    </Link>
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
                        render: (_, row) => <StatusTag status={row.status} />,
                    },
                    {
                        title: 'Chunks',
                        key: 'chunk_count',
                        render: (_, row) => row.chunk_count.toLocaleString(),
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
                            <div className="flex gap-1">
                                {row.source_type === 'url' ? (
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
                                ) : (
                                    <LemonButton
                                        icon={<IconPencil />}
                                        size="small"
                                        tooltip="Edit"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            openEditModal(row)
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
                                        if (window.confirm(`Delete "${row.name}"? Chunks will be removed.`)) {
                                            deleteSource(row.id)
                                        }
                                    }}
                                />
                            </div>
                        ),
                    },
                ]}
                emptyState="No knowledge sources yet. Click 'Add source' to index your first."
            />

            <LemonModal
                isOpen={isCreateModalOpen}
                onClose={closeCreateModal}
                title="Add to business knowledge"
                footer={
                    createTab === 'text' ? (
                        <>
                            <LemonButton onClick={closeCreateModal}>Cancel</LemonButton>
                            <LemonButton type="primary" loading={isTextSourceSubmitting} onClick={submitTextSource}>
                                Add
                            </LemonButton>
                        </>
                    ) : (
                        <>
                            <LemonButton onClick={closeCreateModal}>Cancel</LemonButton>
                            <LemonButton type="primary" loading={isUrlSourceSubmitting} onClick={submitUrlSource}>
                                Fetch and index
                            </LemonButton>
                        </>
                    )
                }
            >
                <LemonTabs
                    activeKey={createTab}
                    onChange={(key) => setCreateTab(key as CreateTab)}
                    tabs={[
                        {
                            key: 'text',
                            label: 'Text',
                            content: (
                                <Form
                                    logic={businessKnowledgeLogic}
                                    formKey="textSource"
                                    className="flex flex-col gap-2"
                                >
                                    <LemonField name="name" label="Name">
                                        <LemonInput placeholder="e.g. Refund policy" />
                                    </LemonField>
                                    <LemonField name="text" label="Content">
                                        <LemonTextArea
                                            placeholder="Paste FAQ, macros, or any text the support agent should be able to cite."
                                            minRows={12}
                                        />
                                    </LemonField>
                                    <p className="text-xs text-muted">
                                        Text is chunked paragraph-by-paragraph and stored in Postgres. The support agent
                                        can find it via SQL — no embeddings or vector DB in this stage.
                                    </p>
                                </Form>
                            ),
                        },
                        {
                            key: 'url',
                            label: 'URL',
                            content: (
                                <Form
                                    logic={businessKnowledgeLogic}
                                    formKey="urlSource"
                                    className="flex flex-col gap-2"
                                >
                                    <LemonField name="name" label="Name">
                                        <LemonInput placeholder="e.g. Product docs – Billing" />
                                    </LemonField>
                                    <LemonField name="url" label="Public URL">
                                        <LemonInput
                                            type="url"
                                            inputMode="url"
                                            placeholder="https://docs.example.com/billing"
                                        />
                                    </LemonField>
                                    <p className="text-xs text-muted">
                                        We fetch the URL once, extract the main text, and index it. Use the refresh
                                        button on the row to re-fetch. Scheduled refresh is Stage 2c.
                                    </p>
                                </Form>
                            ),
                        },
                    ]}
                />
            </LemonModal>

            <LemonModal
                isOpen={isEditModalOpen}
                onClose={closeEditModal}
                title={editingSource ? `Edit "${editingSource.name}"` : 'Edit knowledge source'}
                footer={
                    <>
                        <LemonButton onClick={closeEditModal}>Cancel</LemonButton>
                        <LemonButton
                            type="primary"
                            loading={isEditSourceSubmitting}
                            disabled={editingSourceTextLoading}
                            onClick={submitEditSource}
                        >
                            Save
                        </LemonButton>
                    </>
                }
            >
                {editingSourceTextLoading ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-10" />
                        <LemonSkeleton className="h-60" />
                    </div>
                ) : (
                    <Form logic={businessKnowledgeLogic} formKey="editSource" className="flex flex-col gap-2">
                        <LemonField name="name" label="Name">
                            <LemonInput />
                        </LemonField>
                        <LemonField name="text" label="Content">
                            <LemonTextArea minRows={12} />
                        </LemonField>
                        <p className="text-xs text-muted">
                            Saving rewrites the chunks for this source. Agents won't see the change mid-conversation
                            until they refresh their prompt.
                        </p>
                    </Form>
                )}
            </LemonModal>
        </SceneContent>
    )
}
