import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { userLogic } from 'scenes/userLogic'

import { workflowsLogic } from 'products/workflows/frontend/Workflows/workflowsLogic'

import { SupportEditor, serializeToMarkdown } from '../../components/Editor'
import { TEMPLATE_VARIABLES } from '../../components/Editor/templateVariables'
import { hasVisibleText, quickActionHasReply, quickActionToDoc } from '../../components/QuickActions/applyQuickAction'
import { quickActionsLogic } from '../../components/QuickActions/quickActionsLogic'
import { TicketTags } from '../../components/TicketTags'
import type { QuickActionApi } from '../../generated/api.schemas'
import { QuickActionVisibilityEnumApi } from '../../generated/api.schemas'
import { priorityOptions, statusOptionsWithoutAll } from '../../types'

/** Short human summary of what a quick action does, for the table. */
function summary(quickAction: QuickActionApi): string {
    const parts: string[] = []
    if (quickActionHasReply(quickAction)) {
        parts.push('reply')
    }
    if (quickAction.actions?.status) {
        parts.push(`status → ${quickAction.actions.status}`)
    }
    if (quickAction.actions?.priority) {
        parts.push(`priority → ${quickAction.actions.priority}`)
    }
    if (quickAction.actions?.tags?.length) {
        parts.push(`${quickAction.actions.tags.length} tag${quickAction.actions.tags.length === 1 ? '' : 's'}`)
    }
    if (quickAction.workflow_id) {
        parts.push('runs a workflow')
    }
    return parts.length ? parts.join(', ') : '—'
}

export function QuickActionsSection(): JSX.Element {
    const {
        quickActions,
        quickActionsLoading,
        isModalOpen,
        editingShortId,
        name,
        description,
        visibility,
        statusAction,
        priorityAction,
        tagsAction,
        workflowId,
        saving,
    } = useValues(quickActionsLogic)
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
        setWorkflowId,
        saveQuickAction,
        deleteQuickAction,
    } = useActions(quickActionsLogic)

    const { user } = useValues(userLogic)
    const { workflows, workflowsLoading } = useValues(workflowsLogic)
    const { loadWorkflows } = useActions(workflowsLogic)

    // workflowsLogic doesn't load on mount, so kick the fetch to populate the workflow picker.
    useEffect(() => {
        loadWorkflows()
    }, [loadWorkflows])

    const workflowOptions = workflows
        .filter((w) => w.status === 'active' || w.id === workflowId)
        .map((w) => ({
            value: w.id,
            label:
                w.status === 'active' ? w.name || 'Untitled workflow' : `${w.name || 'Untitled workflow'} (inactive)`,
        }))

    const editorRef = useRef<RichContentEditorType | null>(null)
    const editingQuickAction = quickActions.find((q) => q.short_id === editingShortId) ?? null
    // Only the creator can turn a shared team quick action personal — otherwise it would vanish for
    // everyone else. Mirrors the server-side guard so the invalid option isn't even offered.
    const canMakePersonal =
        !editingQuickAction ||
        editingQuickAction.visibility !== QuickActionVisibilityEnumApi.Team ||
        editingQuickAction.created_by?.id === user?.id

    const handleSave = (): void => {
        const richContent = editorRef.current?.getJSON() ?? null
        // A blank editor still yields a structurally non-empty doc; store an empty reply instead so
        // a workflow-only quick action doesn't carry a junk rich_content.
        const hasReply = !!richContent && hasVisibleText(richContent)
        saveQuickAction({
            content: hasReply ? serializeToMarkdown(richContent) : '',
            rich_content: hasReply ? richContent : {},
        })
    }

    const confirmDelete = (quickAction: QuickActionApi): void => {
        LemonDialog.open({
            title: `Delete "${quickAction.name}"?`,
            description: 'This quick action will no longer be available in the composer.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteQuickAction(quickAction.short_id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-3">
            <p>
                Save things you do often, then trigger them in a conversation by typing <code>/</code> in the message
                box or using the quick action button. A quick action can insert a saved reply, set the ticket's status,
                priority, or tags, and run one of your workflows — any combination.
            </p>
            <div>
                <LemonButton type="primary" icon={<IconPlus />} onClick={openCreateModal}>
                    New quick action
                </LemonButton>
            </div>

            <LemonTable
                dataSource={quickActions}
                loading={quickActionsLoading}
                rowKey="short_id"
                emptyState="No quick actions yet. Create one to speed up your replies."
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, quickAction) => (
                            <div className="flex flex-col">
                                <span className="font-semibold">{quickAction.name}</span>
                                {quickAction.description ? (
                                    <span className="text-xs text-secondary">{quickAction.description}</span>
                                ) : null}
                            </div>
                        ),
                    },
                    {
                        title: 'Visibility',
                        key: 'visibility',
                        render: (_, quickAction) => (
                            <LemonTag
                                type={
                                    quickAction.visibility === QuickActionVisibilityEnumApi.Team ? 'primary' : 'default'
                                }
                            >
                                {quickAction.visibility === QuickActionVisibilityEnumApi.Team ? 'Team' : 'Personal'}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'Does',
                        key: 'summary',
                        render: (_, quickAction) => <span className="text-secondary">{summary(quickAction)}</span>,
                    },
                    {
                        title: '',
                        key: 'row_actions',
                        width: 0,
                        render: (_, quickAction) => (
                            <div className="flex gap-1 justify-end">
                                <LemonButton
                                    size="small"
                                    icon={<IconPencil />}
                                    tooltip="Edit quick action"
                                    onClick={() => openEditModal(quickAction)}
                                />
                                <LemonButton
                                    size="small"
                                    status="danger"
                                    icon={<IconTrash />}
                                    tooltip="Delete quick action"
                                    onClick={() => confirmDelete(quickAction)}
                                />
                            </div>
                        ),
                    },
                ]}
            />

            <LemonModal
                isOpen={isModalOpen}
                onClose={closeModal}
                title={editingShortId ? 'Edit quick action' : 'New quick action'}
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
                            disabledReason={!name.trim() ? 'Give the quick action a name' : undefined}
                        >
                            {editingShortId ? 'Save changes' : 'Create quick action'}
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
                    <div className="grid grid-cols-2 gap-3">
                        <LemonField.Pure label="Description" info="Only shown to your team in the quick action list.">
                            <LemonInput
                                value={description}
                                onChange={setDescription}
                                placeholder="Optional — when to use this"
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Visibility">
                            <LemonSelect
                                value={visibility}
                                onChange={setVisibility}
                                options={[
                                    { value: QuickActionVisibilityEnumApi.Team, label: 'Team — shared with everyone' },
                                    {
                                        value: QuickActionVisibilityEnumApi.Personal,
                                        label: 'Personal — only you',
                                        disabledReason: canMakePersonal
                                            ? undefined
                                            : 'Only the creator can make a shared quick action personal',
                                    },
                                ]}
                            />
                        </LemonField.Pure>
                    </div>

                    <LemonField.Pure
                        label="Reply"
                        info={`Optional. Variables you can use: ${TEMPLATE_VARIABLES.map((v) => `{{${v.token}}}`).join(', ')}`}
                    >
                        <SupportEditor
                            key={editingShortId ?? 'new'}
                            initialContent={editingQuickAction ? quickActionToDoc(editingQuickAction) : null}
                            placeholder="Type a reply to drop into the composer. Use {{customer.name}} to personalize it."
                            onCreate={(editor) => {
                                editorRef.current = editor
                            }}
                            minRows={4}
                        />
                    </LemonField.Pure>
                    <div className="grid grid-cols-2 gap-3">
                        <LemonField.Pure label="Set status" info="Optional — applied when the quick action is used.">
                            <LemonSelect
                                value={statusAction}
                                onChange={setStatusAction}
                                allowClear
                                placeholder="Don't change"
                                options={statusOptionsWithoutAll.map((o) => ({ value: o.value, label: o.label }))}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Set priority" info="Optional — applied when the quick action is used.">
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
                        info="Optional — replaces the ticket's tags when the quick action is used."
                    >
                        <TicketTags tags={tagsAction} onChange={setTagsAction} className="p-0" />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Run a workflow"
                        info="Optional — runs an active workflow against the ticket when the quick action is used. Create and activate workflows in the workflow builder."
                    >
                        <LemonSelect
                            value={workflowId}
                            onChange={setWorkflowId}
                            loading={workflowsLoading}
                            allowClear
                            placeholder="Don't run a workflow"
                            options={workflowOptions}
                        />
                    </LemonField.Pure>
                </div>
            </LemonModal>
        </div>
    )
}
