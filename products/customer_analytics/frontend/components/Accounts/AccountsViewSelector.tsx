import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconChevronDown, IconGlobe, IconPencil, IconPlus, IconUser } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonMenuItem,
    LemonMenuItems,
    LemonModal,
    LemonSegmentedButton,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { accountsViewsLogic } from './accountsViewsLogic'

export function AccountsViewSelector(): JSX.Element {
    const { views, currentView, isDirty, viewsLoading } = useValues(accountsViewsLogic)
    const { selectView, updateView, setViewToDelete, setViewToEdit, setIsCreating } = useActions(accountsViewsLogic)

    const menuItems: LemonMenuItems = [
        {
            items: views.map(
                (view) =>
                    ({
                        label: view.name,
                        icon: <ViewVisibilityIcon view={view} />,
                        active: currentView?.id === view.id,
                        onClick: () => selectView(view.id),
                        sideAction: {
                            icon: <IconPencil />,
                            tooltip: 'Manage view',
                            dropdown: {
                                overlay: (
                                    <>
                                        <LemonButton size="small" fullWidth onClick={() => setViewToEdit(view.id)}>
                                            Edit
                                        </LemonButton>
                                        <LemonButton
                                            size="small"
                                            fullWidth
                                            status="danger"
                                            onClick={() => setViewToDelete(view.id)}
                                        >
                                            Delete
                                        </LemonButton>
                                    </>
                                ),
                            },
                        },
                    }) as LemonMenuItem
            ),
        },
        {
            items: [{ label: 'Save as new view...', icon: <IconPlus />, onClick: () => setIsCreating(true) }],
        },
    ]

    return (
        <div className="flex items-center gap-2">
            {views.length > 0 ? (
                <LemonMenu items={menuItems} closeOnClickInside>
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {currentView ? (
                            <>
                                <ViewVisibilityIcon view={currentView} />
                                <span className="ml-2">{currentView.name}</span>
                            </>
                        ) : (
                            'Select view'
                        )}
                    </LemonButton>
                </LemonMenu>
            ) : (
                <LemonButton
                    icon={<IconPlus />}
                    size="small"
                    type="secondary"
                    onClick={() => setIsCreating(true)}
                    data-attr="accounts-save-view"
                >
                    Save current view
                </LemonButton>
            )}

            {currentView && isDirty && (
                <LemonButton
                    size="small"
                    type="secondary"
                    tooltip="Update this view with the current configuration"
                    loading={viewsLoading}
                    onClick={() => updateView({ id: currentView.id, updates: {} })}
                    data-attr="accounts-update-view"
                >
                    Update "{currentView.name}"
                </LemonButton>
            )}

            <ViewModal />
            <DeleteViewModal />
        </div>
    )
}

function ViewModal(): JSX.Element {
    const { isCreating, viewToEdit, isViewFormSubmitting, viewsLoading } = useValues(accountsViewsLogic)
    const { submitViewForm, resetViewForm, setIsCreating, setViewToEdit } = useActions(accountsViewsLogic)
    const isEditing = !!viewToEdit
    const isSaving = isViewFormSubmitting || viewsLoading

    const close = (): void => {
        setIsCreating(false)
        setViewToEdit(null)
        resetViewForm()
    }

    return (
        <LemonModal
            isOpen={isCreating || isEditing}
            onClose={close}
            title={isEditing ? 'Edit view' : 'Save as new view'}
            description={
                isEditing
                    ? undefined
                    : 'Save the current filters, columns, ordering, and overview tiles as a reusable view'
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={close}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitViewForm}
                        loading={isSaving}
                        disabledReason={isSaving ? 'Saving…' : undefined}
                    >
                        {isEditing ? 'Save changes' : 'Save view'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={accountsViewsLogic} formKey="viewForm">
                <div className="space-y-4">
                    <LemonField name="name" label="View name">
                        <LemonInput
                            placeholder="e.g. Enterprise accounts"
                            autoFocus
                            onPressEnter={isSaving ? undefined : submitViewForm}
                        />
                    </LemonField>
                    <LemonField name="visibility" label="Visibility">
                        <LemonSegmentedButton
                            options={[
                                { value: 'private', label: 'Private (only visible to me)', icon: <IconUser /> },
                                { value: 'shared', label: 'Shared with team', icon: <IconGlobe /> },
                            ]}
                            fullWidth
                        />
                    </LemonField>
                </div>
            </Form>
        </LemonModal>
    )
}

function DeleteViewModal(): JSX.Element {
    const { views, viewToDelete, viewsLoading } = useValues(accountsViewsLogic)
    const { deleteView, setViewToDelete } = useActions(accountsViewsLogic)
    const view = views.find((v) => v.id === viewToDelete)

    return (
        <LemonModal
            isOpen={!!viewToDelete}
            onClose={() => setViewToDelete(null)}
            title="Delete view"
            description={`Are you sure you want to delete the view "${view?.name ?? ''}"?`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setViewToDelete(null)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        onClick={() => {
                            if (viewToDelete) {
                                deleteView({ id: viewToDelete })
                            }
                        }}
                        loading={viewsLoading}
                        disabledReason={viewsLoading ? 'Deleting…' : undefined}
                    >
                        Delete
                    </LemonButton>
                </>
            }
        />
    )
}

function ViewVisibilityIcon({ view }: { view: ColumnConfigurationApi }): JSX.Element {
    return view.visibility === 'private' ? (
        <Tooltip title="Only you can see this view.">
            <IconUser />
        </Tooltip>
    ) : (
        <Tooltip title="Everyone on your team can see this view.">
            <IconGlobe />
        </Tooltip>
    )
}
