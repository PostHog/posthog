import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconBook, IconPencil, IconPlusSmall, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonModal, LemonSelect, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
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

function CrawlModeHelp(): JSX.Element {
    const { urlSource } = useValues(businessKnowledgeLogic)
    if (urlSource.crawl_mode === 'single') {
        return (
            <p className="text-xs text-muted">
                Fetch this URL once and index its main text. Use the refresh button on the row to re-fetch.
            </p>
        )
    }
    if (urlSource.crawl_mode === 'sitemap') {
        return (
            <p className="text-xs text-muted">
                Read sitemap.xml at this URL (or <code>/sitemap.xml</code> at its origin) and index each listed page.
                Scheduled refresh is Stage 5.
            </p>
        )
    }
    return (
        <p className="text-xs text-muted">
            BFS-crawl from this URL staying on the same scheme + host + port. Honors robots.txt.
        </p>
    )
}

function CrawlConfigFields({ crawlMode }: { crawlMode: string }): JSX.Element | null {
    if (crawlMode === 'single') {
        return null
    }
    return (
        <>
            <LemonField
                name="include_globs"
                label="Include globs"
                info="URL path patterns to include. One per line or comma-separated. Empty = include everything."
            >
                <LemonTextArea minRows={2} placeholder={'/docs/*\n/handbook/*'} />
            </LemonField>
            <LemonField
                name="exclude_globs"
                label="Exclude globs"
                info="URL path patterns to exclude. Applied after include."
            >
                <LemonTextArea minRows={2} placeholder="/docs/private/*" />
            </LemonField>
            <div className="flex gap-2">
                <LemonField name="max_pages" label="Max pages" className="flex-1">
                    <LemonInput type="number" min={1} max={500} />
                </LemonField>
                {crawlMode === 'same_origin' && (
                    <LemonField name="max_depth" label="Max depth" className="flex-1">
                        <LemonInput type="number" min={0} max={5} />
                    </LemonField>
                )}
            </div>
        </>
    )
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
        isFileSourceSubmitting,
        isEditSourceSubmitting,
        isEditUrlSourceSubmitting,
        urlSource,
        editUrlSource,
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
        submitFileSource,
        setFileSourceValue,
        submitEditSource,
        submitEditUrlSource,
    } = useActions(businessKnowledgeLogic)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text, public URLs, or files your AI support agent can cite when answering customer tickets."
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
                                <strong>{row.name}</strong>
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
                        render: (_, row) => <StatusTag status={row.status} />,
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

            <LemonModal
                isOpen={isCreateModalOpen}
                onClose={closeCreateModal}
                width={800}
                title="Add to business knowledge"
                footer={
                    <>
                        <LemonButton onClick={closeCreateModal}>Cancel</LemonButton>
                        {createTab === 'text' ? (
                            <LemonButton type="primary" loading={isTextSourceSubmitting} onClick={submitTextSource}>
                                Add
                            </LemonButton>
                        ) : createTab === 'url' ? (
                            <LemonButton type="primary" loading={isUrlSourceSubmitting} onClick={submitUrlSource}>
                                Fetch and index
                            </LemonButton>
                        ) : (
                            <LemonButton type="primary" loading={isFileSourceSubmitting} onClick={submitFileSource}>
                                Upload and index
                            </LemonButton>
                        )}
                    </>
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
                                    <LemonField name="url" label="Entry URL">
                                        <LemonInput
                                            type="url"
                                            inputMode="url"
                                            placeholder="https://docs.example.com/billing or https://example.com/sitemap.xml"
                                        />
                                    </LemonField>
                                    <LemonField name="crawl_mode" label="Mode">
                                        <LemonSelect
                                            options={[
                                                {
                                                    value: 'single',
                                                    label: 'Single page',
                                                },
                                                {
                                                    value: 'sitemap',
                                                    label: 'Sitemap.xml',
                                                },
                                                {
                                                    value: 'same_origin',
                                                    label: 'Same-origin crawl',
                                                },
                                            ]}
                                        />
                                    </LemonField>
                                    <CrawlModeHelp />
                                    <CrawlConfigFields crawlMode={urlSource.crawl_mode} />
                                </Form>
                            ),
                        },
                        {
                            key: 'file',
                            label: 'File',
                            content: (
                                <Form
                                    logic={businessKnowledgeLogic}
                                    formKey="fileSource"
                                    className="flex flex-col gap-2"
                                >
                                    <LemonField name="file" label="File">
                                        <LemonFileInput
                                            accept=".pdf,.docx,.md,.markdown,.txt,.csv"
                                            multiple={false}
                                            callToAction="Drop a file here or click to browse"
                                            showUploadedFiles
                                            onChange={(files) => {
                                                const file = files[0] ?? null
                                                setFileSourceValue('file', file)
                                                if (file) {
                                                    const nameWithoutExt = file.name.replace(/\.[^.]+$/, '')
                                                    setFileSourceValue('name', nameWithoutExt)
                                                }
                                            }}
                                        />
                                    </LemonField>
                                    <LemonField name="name" label="Name">
                                        <LemonInput placeholder="Auto-filled from filename" />
                                    </LemonField>
                                    <p className="text-xs text-muted">
                                        PDF, DOCX, Markdown, CSV, or plain text. Max 50 MB. The file is parsed into text
                                        and chunked — the original file is not stored.
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
                            loading={
                                editingSource?.source_type === 'url'
                                    ? isEditUrlSourceSubmitting
                                    : isEditSourceSubmitting
                            }
                            disabled={editingSource?.source_type === 'text' && editingSourceTextLoading}
                            onClick={editingSource?.source_type === 'url' ? submitEditUrlSource : submitEditSource}
                        >
                            Save
                        </LemonButton>
                    </>
                }
            >
                {editingSource?.source_type === 'url' ? (
                    <Form logic={businessKnowledgeLogic} formKey="editUrlSource" className="flex flex-col gap-2">
                        <LemonField name="name" label="Name">
                            <LemonInput />
                        </LemonField>
                        <LemonField name="url" label="URL">
                            <LemonInput placeholder="https://docs.example.com" />
                        </LemonField>
                        <LemonField name="crawl_mode" label="Crawl mode">
                            <LemonSelect
                                options={[
                                    { value: 'single', label: 'Single page' },
                                    { value: 'sitemap', label: 'Sitemap' },
                                    { value: 'same_origin', label: 'Crawl same origin' },
                                ]}
                            />
                        </LemonField>
                        <CrawlConfigFields crawlMode={editUrlSource.crawl_mode} />
                        <p className="text-xs text-muted">
                            Changing the URL or crawl settings will trigger a re-crawl.
                        </p>
                    </Form>
                ) : editingSource?.source_type === 'text' && editingSourceTextLoading ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-10" />
                        <LemonSkeleton className="h-60" />
                    </div>
                ) : (
                    <Form logic={businessKnowledgeLogic} formKey="editSource" className="flex flex-col gap-2">
                        <LemonField name="name" label="Name">
                            <LemonInput />
                        </LemonField>
                        {editingSource?.source_type === 'text' && (
                            <LemonField name="text" label="Content">
                                <LemonTextArea minRows={12} />
                            </LemonField>
                        )}
                        {editingSource?.source_type === 'file' && editingSource.original_filename && (
                            <p className="text-xs text-muted">
                                Uploaded file: {editingSource.original_filename}. To replace the content, delete this
                                source and upload a new file.
                            </p>
                        )}
                        {editingSource?.source_type === 'text' && (
                            <p className="text-xs text-muted">
                                Saving rewrites the chunks for this source. Agents won't see the change mid-conversation
                                until they refresh their prompt.
                            </p>
                        )}
                    </Form>
                )}
            </LemonModal>
        </SceneContent>
    )
}
