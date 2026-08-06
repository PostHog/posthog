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

import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { accountsViewsLogic } from './accountsViewsLogic'

export function AccountsViewSelector(): JSX.Element {
    const { views, currentView, isDirty, viewsLoading, canEditCurrentView, user } = useValues(accountsViewsLogic)
    const { selectView, updateView, setViewToDelete, setViewToRename, setIsCreating } = useActions(accountsViewsLogic)

    const menuItems: LemonMenuItems = [
        {
            items: views.map((view) => {
                const canEdit = view.created_by === user?.id
                return {
                    label: view.name,
                    icon: <ViewVisibilityIcon view={view} />,
                    active: currentView?.id === view.id,
                    onClick: () => selectView(view.id),
                    ...(canEdit && {
                        sideAction: {
                            icon: <IconPencil />,
                            tooltip: 'Manage view',
                            dropdown: {
                                overlay: (
                                    <>
                                        <LemonButton size="small" fullWidth onClick={() => setViewToRename(view.id)}>
                                            Rename
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
                    }),
                } as LemonMenuItem
            }),
        },
        {
            items: [{ label: 'Save as new view...', icon: <IconPlus />, onClick: () => setIsCreating(true) }],
        },
    ]

    return (
        <div className="flex items-center gap-2">
            {currentView ? (
                <LemonMenu items={menuItems} closeOnClickInside>
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        <ViewVisibilityIcon view={currentView} />
                        <span className="ml-2">{currentView.name}</span>
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
                    disabledReason={!canEditCurrentView ? 'You can only edit views you created' : undefined}
                    loading={viewsLoading}
                    onClick={() => updateView({ id: currentView.id, updates: {} })}
                    data-attr="accounts-update-view"
                >
                    Update "{currentView.name}"
                </LemonButton>
            )}

            <CreateViewModal />
            <RenameViewModal />
            <DeleteViewModal />
        </div>
    )
}

function CreateViewModal(): JSX.Element {
    const { isCreating, isNewViewFormSubmitting } = useValues(accountsViewsLogic)
    const { submitNewViewForm, resetNewViewForm, setIsCreating } = useActions(accountsViewsLogic)

    const close = (): void => {
        setIsCreating(false)
        resetNewViewForm()
    }

    return (
        <LemonModal
            isOpen={isCreating}
            onClose={close}
            title="Save as new view"
            description="Save the current filters, columns, ordering, and overview tiles as a reusable view"
            footer={
                <>
                    <LemonButton type="secondary" onClick={close}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitNewViewForm}
                        loading={isNewViewFormSubmitting}
                        disabledReason={isNewViewFormSubmitting ? 'Saving…' : undefined}
                    >
                        Save view
                    </LemonButton>
                </>
            }
        >
            <Form logic={accountsViewsLogic} formKey="newViewForm">
                <div className="space-y-4">
                    <LemonField name="name" label="View name">
                        <LemonInput placeholder="e.g. Enterprise accounts" autoFocus onPressEnter={submitNewViewForm} />
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

function RenameViewModal(): JSX.Element {
    const { views, viewToRename, viewsLoading } = useValues(accountsViewsLogic)
    const { setViewToRename, submitRenameViewForm, resetRenameViewForm } = useActions(accountsViewsLogic)
    const view = views.find((v) => v.id === viewToRename)

    const close = (): void => {
        setViewToRename(null)
        resetRenameViewForm()
    }

    return (
        <LemonModal
            isOpen={!!viewToRename}
            onClose={close}
            title="Rename view"
            footer={
                <>
                    <LemonButton type="secondary" onClick={close}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitRenameViewForm}
                        loading={viewsLoading}
                        disabledReason={viewsLoading ? 'Saving…' : undefined}
                    >
                        Rename
                    </LemonButton>
                </>
            }
        >
            <Form logic={accountsViewsLogic} formKey="renameViewForm">
                <LemonField name="name" label="View name">
                    <LemonInput placeholder={view?.name} autoFocus onPressEnter={submitRenameViewForm} />
                </LemonField>
            </Form>
        </LemonModal>
    )
}

function DeleteViewModal(): JSX.Element {
    const { views, viewToDelete } = useValues(accountsViewsLogic)
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
                                setViewToDelete(null)
                            }
                        }}
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
