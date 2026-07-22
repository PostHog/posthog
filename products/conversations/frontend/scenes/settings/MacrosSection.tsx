import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { userLogic } from 'scenes/userLogic'

import { SupportEditor, serializeToMarkdown } from '../../components/Editor'
import { MACRO_VARIABLES } from '../../components/Editor/macroVariables'
import { macroToDoc } from '../../components/Macros/applyMacro'
import { macrosLogic } from '../../components/Macros/macrosLogic'
import { TicketTags } from '../../components/TicketTags'
import type { MacroApi } from '../../generated/api.schemas'
import { MacroVisibilityEnumApi } from '../../generated/api.schemas'
import { priorityOptions, statusOptionsWithoutAll } from '../../types'

/** Short human summary of the ticket actions a macro applies, for the table. */
function actionsSummary(macro: MacroApi): string {
    const parts: string[] = []
    if (macro.actions?.status) {
        parts.push(`status → ${macro.actions.status}`)
    }
    if (macro.actions?.priority) {
        parts.push(`priority → ${macro.actions.priority}`)
    }
    if (macro.actions?.tags?.length) {
        parts.push(`${macro.actions.tags.length} tag${macro.actions.tags.length === 1 ? '' : 's'}`)
    }
    return parts.length ? parts.join(', ') : 'Text only'
}

export function MacrosSection(): JSX.Element {
    const {
        macros,
        macrosLoading,
        isModalOpen,
        editingShortId,
        name,
        description,
        visibility,
        statusAction,
        priorityAction,
        tagsAction,
        saving,
    } = useValues(macrosLogic)
    const {
        openCreateModal,
        openEditModal,
        closeModal,
        setName,
        setDescription,
        setVisibility,
        setStatusAction,
        setPriorityAction,
        setTagsAction,
        saveMacro,
        deleteMacro,
    } = useActions(macrosLogic)

    const { user } = useValues(userLogic)

    const editorRef = useRef<RichContentEditorType | null>(null)
    const editingMacro = macros.find((m) => m.short_id === editingShortId) ?? null
    // Only the creator can turn a shared team macro personal — otherwise it would vanish for
    // everyone else. Mirrors the server-side guard so the invalid option isn't even offered.
    const canMakePersonal =
        !editingMacro ||
        editingMacro.visibility !== MacroVisibilityEnumApi.Team ||
        editingMacro.created_by?.id === user?.id

    const handleSave = (): void => {
        const richContent = editorRef.current?.getJSON() ?? null
        saveMacro({
            content: richContent ? serializeToMarkdown(richContent) : '',
            rich_content: richContent,
        })
    }

    const confirmDelete = (macro: MacroApi): void => {
        LemonDialog.open({
            title: `Delete "${macro.name}"?`,
            description: 'This macro will no longer be available in the composer.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteMacro(macro.short_id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-3">
            <p>
                Save replies you send often, then drop them into a conversation by typing <code>/</code> in the message
                box or using the macro button. A macro can also set the ticket's status, priority, or tags, and fill in
                details like the customer's name automatically.
            </p>
            <div>
                <LemonButton type="primary" icon={<IconPlus />} onClick={openCreateModal}>
                    New macro
                </LemonButton>
            </div>

            <LemonTable
                dataSource={macros}
                loading={macrosLoading}
                rowKey="short_id"
                emptyState="No macros yet. Create one to speed up your replies."
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, macro) => (
                            <div className="flex flex-col">
                                <span className="font-semibold">{macro.name}</span>
                                {macro.description ? (
                                    <span className="text-xs text-secondary">{macro.description}</span>
                                ) : null}
                            </div>
                        ),
                    },
                    {
                        title: 'Visibility',
                        key: 'visibility',
                        render: (_, macro) => (
                            <LemonTag type={macro.visibility === MacroVisibilityEnumApi.Team ? 'primary' : 'default'}>
                                {macro.visibility === MacroVisibilityEnumApi.Team ? 'Team' : 'Personal'}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'Applies',
                        key: 'actions_summary',
                        render: (_, macro) => <span className="text-secondary">{actionsSummary(macro)}</span>,
                    },
                    {
                        title: '',
                        key: 'row_actions',
                        width: 0,
                        render: (_, macro) => (
                            <div className="flex gap-1 justify-end">
                                <LemonButton
                                    size="small"
                                    icon={<IconPencil />}
                                    tooltip="Edit macro"
                                    onClick={() => openEditModal(macro)}
                                />
                                <LemonButton
                                    size="small"
                                    status="danger"
                                    icon={<IconTrash />}
                                    tooltip="Delete macro"
                                    onClick={() => confirmDelete(macro)}
                                />
                            </div>
                        ),
                    },
                ]}
            />

            <LemonModal
                isOpen={isModalOpen}
                onClose={closeModal}
                title={editingShortId ? 'Edit macro' : 'New macro'}
                width={640}
                footer={
                    <div className="flex gap-2 justify-end">
                        <LemonButton
                            type="secondary"
                            onClick={closeModal}
                            disabledReason={saving ? 'Saving...' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={handleSave}
                            loading={saving}
                            disabledReason={!name.trim() ? 'Give the macro a name' : undefined}
                        >
                            {editingShortId ? 'Save changes' : 'Create macro'}
                        </LemonButton>
                    </div>
                }
            >
                <div className="flex flex-col gap-3">
                    <LemonField.Pure label="Name">
                        <LemonInput
                            value={name}
                            onChange={setName}
                            placeholder="e.g. Ask for reproduction steps"
                            autoFocus
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Description" info="Only shown to your team in the macro list.">
                        <LemonInput
                            value={description}
                            onChange={setDescription}
                            placeholder="Optional — when to use this macro"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Visibility">
                        <LemonSelect
                            value={visibility}
                            onChange={setVisibility}
                            options={[
                                { value: MacroVisibilityEnumApi.Team, label: 'Team — shared with everyone' },
                                {
                                    value: MacroVisibilityEnumApi.Personal,
                                    label: 'Personal — only you',
                                    disabledReason: canMakePersonal
                                        ? undefined
                                        : 'Only the creator can make a shared macro personal',
                                },
                            ]}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Reply"
                        info={`Variables you can use: ${MACRO_VARIABLES.map((v) => `{{${v.token}}}`).join(', ')}`}
                    >
                        <SupportEditor
                            key={editingShortId ?? 'new'}
                            initialContent={editingMacro ? macroToDoc(editingMacro) : null}
                            placeholder="Type the reply. Use {{customer.name}} and other variables to personalize it."
                            onCreate={(editor) => {
                                editorRef.current = editor
                            }}
                            minRows={4}
                        />
                    </LemonField.Pure>
                    <div className="grid grid-cols-2 gap-3">
                        <LemonField.Pure label="Set status" info="Optional — applied when the macro is used.">
                            <LemonSelect
                                value={statusAction}
                                onChange={setStatusAction}
                                allowClear
                                placeholder="Don't change"
                                options={statusOptionsWithoutAll.map((o) => ({ value: o.value, label: o.label }))}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Set priority" info="Optional — applied when the macro is used.">
                            <LemonSelect
                                value={priorityAction}
                                onChange={setPriorityAction}
                                allowClear
                                placeholder="Don't change"
                                options={priorityOptions.map((o) => ({ value: o.value, label: o.label }))}
                            />
                        </LemonField.Pure>
                    </div>
                    <LemonField.Pure
                        label="Set tags"
                        info="Optional — replaces the ticket's tags when the macro is used."
                    >
                        <TicketTags tags={tagsAction} onChange={setTagsAction} className="p-0" />
                    </LemonField.Pure>
                </div>
            </LemonModal>
        </div>
    )
}
