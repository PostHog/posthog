import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconBook, IconPencil, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { KnowledgeSource, businessKnowledgeLogic } from './businessKnowledgeLogic'

export const scene: SceneExport = {
    component: BusinessKnowledgeScene,
    logic: businessKnowledgeLogic,
}

function StatusTag({ status }: { status: KnowledgeSource['status'] }): JSX.Element {
    const variant =
        status === 'ready' ? 'success' : status === 'error' ? 'danger' : status === 'processing' ? 'warning' : 'muted'
    return <LemonTag type={variant}>{status}</LemonTag>
}

export function BusinessKnowledgeScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const {
        sources,
        sourcesLoading,
        isCreateModalOpen,
        isEditModalOpen,
        editingSource,
        editingSourceTextLoading,
        readyCount,
        totalChunks,
        isTextSourceSubmitting,
        isEditSourceSubmitting,
    } = useValues(businessKnowledgeLogic)
    const {
        openCreateModal,
        closeCreateModal,
        openEditModal,
        closeEditModal,
        deleteSource,
        submitTextSource,
        submitEditSource,
    } = useActions(businessKnowledgeLogic)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text your AI support agent can cite when answering customer tickets. URLs and files come in later stages."
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBook /> }}
                actions={
                    <LemonButton type="primary" icon={<IconPlusSmall />} onClick={openCreateModal}>
                        Add text
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
                    onClick: () => openEditModal(row),
                    style: { cursor: 'pointer' },
                })}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, row) => <strong>{row.name}</strong>,
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
                        title: '',
                        key: 'actions',
                        width: 0,
                        render: (_, row) => (
                            <div className="flex gap-1">
                                <LemonButton
                                    icon={<IconPencil />}
                                    size="small"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        openEditModal(row)
                                    }}
                                />
                                <LemonButton
                                    icon={<IconTrash />}
                                    status="danger"
                                    size="small"
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
                emptyState="No knowledge sources yet. Click 'Add text' to index your first."
            />

            <LemonModal
                isOpen={isCreateModalOpen}
                onClose={closeCreateModal}
                title="Add text to business knowledge"
                footer={
                    <>
                        <LemonButton onClick={closeCreateModal}>Cancel</LemonButton>
                        <LemonButton type="primary" loading={isTextSourceSubmitting} onClick={submitTextSource}>
                            Add
                        </LemonButton>
                    </>
                }
            >
                <Form logic={businessKnowledgeLogic} formKey="textSource" className="flex flex-col gap-2">
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
                        Text is chunked paragraph-by-paragraph and stored in Postgres. The support agent can find it via
                        SQL — no embeddings or vector DB in this stage.
                    </p>
                </Form>
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
