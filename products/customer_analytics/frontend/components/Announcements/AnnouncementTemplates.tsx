import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonMenu,
    LemonModal,
    LemonTable,
    LemonTableColumns,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { AnnouncementTemplateApi } from '../../generated/api.schemas'
import { announcementTemplatesLogic } from './announcementTemplatesLogic'

function TemplateEditorModal(): JSX.Element {
    const { editorOpen, editingTemplateId, formName, formMessage, saving, saveDisabledReason } =
        useValues(announcementTemplatesLogic)
    const { setFormName, setFormMessage, saveTemplate, closeEditor } = useActions(announcementTemplatesLogic)

    return (
        <LemonModal
            isOpen={editorOpen}
            onClose={closeEditor}
            title={editingTemplateId ? 'Edit template' : 'Save as template'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeEditor}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveTemplate}
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        data-attr="save-announcement-template"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2 w-[520px] max-w-full">
                <LemonInput value={formName} onChange={setFormName} placeholder="Template name" autoFocus />
                <LemonTextArea
                    value={formMessage}
                    onChange={setFormMessage}
                    placeholder="Message body"
                    minRows={4}
                />
            </div>
        </LemonModal>
    )
}

function ManageTemplatesModal(): JSX.Element {
    const { manageModalOpen, templates, templatesLoading } = useValues(announcementTemplatesLogic)
    const { closeManageModal, openCreateEditor, openEditEditor, deleteTemplate } =
        useActions(announcementTemplatesLogic)

    const confirmDelete = (template: AnnouncementTemplateApi): void => {
        LemonDialog.open({
            title: `Delete "${template.name}"?`,
            description: 'This template will be removed from the picker.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteTemplate(template.id),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const columns: LemonTableColumns<AnnouncementTemplateApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, template) => <span className="font-medium">{template.name}</span>,
        },
        {
            title: 'Message',
            key: 'message',
            render: (_, template) => <span className="truncate max-w-xs inline-block">{template.message}</span>,
        },
        {
            title: 'Updated',
            key: 'updated_at',
            render: (_, template) => (template.updated_at ? <TZLabel time={template.updated_at} /> : '—'),
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            render: (_, template) => (
                <div className="flex gap-1 justify-end">
                    <LemonButton size="small" type="secondary" onClick={() => openEditEditor(template)}>
                        Edit
                    </LemonButton>
                    <LemonButton size="small" status="danger" onClick={() => confirmDelete(template)}>
                        Delete
                    </LemonButton>
                </div>
            ),
        },
    ]

    return (
        <LemonModal isOpen={manageModalOpen} onClose={closeManageModal} title="Announcement templates" width={720}>
            <div className="flex flex-col gap-2">
                <div className="flex justify-end">
                    <LemonButton type="secondary" size="small" onClick={() => openCreateEditor('')}>
                        New template
                    </LemonButton>
                </div>
                <LemonTable
                    dataSource={templates}
                    loading={templatesLoading}
                    rowKey="id"
                    columns={columns}
                    emptyState="No templates yet"
                />
            </div>
        </LemonModal>
    )
}

// The template toolbar for the announcement composer: insert a saved message, save the
// current draft as a template, and manage the library. Also renders the two modals.
export function TemplateActions({
    currentMessage,
    onInsert,
}: {
    currentMessage: string
    onInsert: (message: string) => void
}): JSX.Element {
    const { templates, templatesLoading } = useValues(announcementTemplatesLogic)
    const { openCreateEditor, openManageModal } = useActions(announcementTemplatesLogic)

    return (
        <div className="flex gap-2 items-center flex-wrap">
            {templates.length > 0 ? (
                <LemonMenu
                    items={templates.map((template) => ({
                        label: template.name,
                        onClick: () => onInsert(template.message),
                    }))}
                    placement="bottom-start"
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        disabledReason={templatesLoading ? 'Loading templates…' : undefined}
                    >
                        Insert template
                    </LemonButton>
                </LemonMenu>
            ) : (
                <LemonButton
                    type="secondary"
                    size="small"
                    disabledReason={templatesLoading ? 'Loading templates…' : 'No templates yet'}
                >
                    Insert template
                </LemonButton>
            )}
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => openCreateEditor(currentMessage)}
                disabledReason={currentMessage.trim() ? undefined : 'Write a message first'}
                data-attr="save-as-announcement-template"
            >
                Save as template
            </LemonButton>
            <LemonButton type="secondary" size="small" onClick={openManageModal}>
                Manage templates
            </LemonButton>
            <TemplateEditorModal />
            <ManageTemplatesModal />
        </div>
    )
}
