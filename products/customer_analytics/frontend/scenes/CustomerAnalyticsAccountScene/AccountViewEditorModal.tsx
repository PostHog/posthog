import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonSelect,
    LemonTag,
} from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    getAccountViewComponentByKind,
    listAvailableAccountViewComponents,
    type AccountViewComponentKind,
} from '../../components/Accounts/accountViewComponents'
import { AccountViewEditorComponentItem } from './AccountViewEditorComponentItem'
import { accountViewsLogic } from './accountViewsLogic'

interface AccountViewEditorModalProps {
    projectId: number
}

export function AccountViewEditorModal({ projectId }: AccountViewEditorModalProps): JSX.Element {
    const logic = accountViewsLogic({ projectId })
    const { featureFlags } = useValues(featureFlagLogic)
    const { editorOpen, editorDraft, editorSaving, editorConflict, editingView } = useValues(logic)
    const {
        setEditorOpen,
        setEditorName,
        addEditorComponent,
        duplicateEditorComponent,
        removeEditorComponent,
        reorderEditorComponent,
        saveEditor,
        reloadEditor,
        deleteView,
    } = useActions(logic)
    const availableComponents = listAvailableAccountViewComponents(featureFlags)
    const saveDisabledReason = !editorDraft.name.trim()
        ? 'Enter a view name'
        : editorDraft.components.length === 0
          ? 'Add at least one component'
          : undefined

    const confirmDelete = (): void => {
        if (!editingView) {
            return
        }
        LemonDialog.open({
            title: `Delete "${editingView.name}"?`,
            description: 'This removes the view from your account tabs.',
            primaryButton: {
                children: 'Delete view',
                status: 'danger',
                onClick: () => deleteView(editingView.id, editingView.version),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <LemonModal
            isOpen={editorOpen}
            onClose={() => setEditorOpen(false)}
            title={editingView ? 'Edit view' : 'Add view'}
            width={640}
            footer={
                <>
                    {editingView ? (
                        <LemonButton
                            status="danger"
                            type="secondary"
                            icon={<IconTrash />}
                            onClick={confirmDelete}
                            loading={editorSaving}
                            disabledReason={editorSaving ? 'Saving changes' : undefined}
                            className="mr-auto"
                            data-attr="account-view-delete"
                        >
                            Delete view
                        </LemonButton>
                    ) : null}
                    <LemonButton type="secondary" onClick={() => setEditorOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveEditor}
                        loading={editorSaving}
                        disabledReason={saveDisabledReason}
                        data-attr="account-view-save"
                    >
                        {editingView ? 'Save changes' : 'Create view'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {editorConflict ? (
                    <LemonBanner type="warning" action={{ children: 'Reload view', onClick: reloadEditor }}>
                        This view changed since you opened it. Reload the latest version before saving.
                    </LemonBanner>
                ) : null}
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="account-view-name">View name</LemonLabel>
                    <LemonInput
                        id="account-view-name"
                        value={editorDraft.name}
                        onChange={setEditorName}
                        placeholder="Account overview"
                        autoFocus
                        data-attr="account-view-name"
                    />
                </div>
                <div className="flex flex-wrap items-end gap-2">
                    <div className="flex min-w-56 flex-1 flex-col gap-1">
                        <LemonLabel>Components</LemonLabel>
                        <LemonSelect<AccountViewComponentKind>
                            value={null}
                            allowClear
                            onChange={(kind) => kind && addEditorComponent(kind)}
                            options={availableComponents.map((component) => ({
                                value: component.kind,
                                label: component.label,
                            }))}
                            placeholder="Choose a component"
                        />
                    </div>
                    <LemonTag type="muted">{editorDraft.components.length} added</LemonTag>
                </div>
                <div className="flex flex-col gap-2">
                    {editorDraft.components.length === 0 ? (
                        <div className="rounded border border-dashed p-4 text-center text-secondary">
                            Add the account sections you want to show in this view.
                        </div>
                    ) : (
                        <DndContext
                            onDragEnd={({ active, over }) => {
                                if (over) {
                                    reorderEditorComponent(String(active.id), String(over.id))
                                }
                            }}
                            modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                        >
                            <SortableContext
                                items={editorDraft.components.map((component) => component.nodeId)}
                                strategy={verticalListSortingStrategy}
                            >
                                <div className="flex flex-col gap-2">
                                    {editorDraft.components.map((component) => {
                                        const definition = getAccountViewComponentByKind(component.kind)
                                        return (
                                            <AccountViewEditorComponentItem
                                                key={component.nodeId}
                                                component={component}
                                                label={component.title ?? definition?.label ?? component.kind}
                                                disabled={editorSaving}
                                                onDuplicate={() => duplicateEditorComponent(component.nodeId)}
                                                onRemove={() => removeEditorComponent(component.nodeId)}
                                            />
                                        )
                                    })}
                                </div>
                            </SortableContext>
                        </DndContext>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
