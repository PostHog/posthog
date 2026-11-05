import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconChevronDown, IconGlobe, IconPencil, IconPlus, IconTrash, IconUser } from '@posthog/icons'
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

import { AccountNotesViewsLogicProps, accountNotesViewsLogic } from './accountNotesViewsLogic'

interface AccountNotesViewSelectorProps {
    logicProps?: AccountNotesViewsLogicProps
}

export function AccountNotesViewSelector({ logicProps = {} }: AccountNotesViewSelectorProps): JSX.Element {
    const logic = accountNotesViewsLogic(logicProps)
    const { views, currentView, isDirty, canEditCurrentView, viewsLoading, viewsLoadError } = useValues(logic)
    const { selectView, clearView, updateView, setViewToDelete, setViewToEdit, setIsCreating, loadViews } =
        useActions(logic)

    const menuItems: LemonMenuItems = [
        {
            items: [
                {
                    label: 'All notes',
                    active: !currentView,
                    onClick: clearView,
                } as LemonMenuItem,
                ...views.map(
                    (view) =>
                        ({
                            label: view.name,
                            icon: <ViewVisibilityIcon view={view} />,
                            active: currentView?.id === view.id,
                            onClick: () => selectView(view.id),
                        }) as LemonMenuItem
                ),
            ],
        },
        {
            items: [
                {
                    label: 'Save as new view...',
                    icon: <IconPlus />,
                    onClick: () => setIsCreating(true),
                },
            ],
        },
    ]

    return (
        <div className="flex items-center gap-2" data-attr="account-notes-views">
            {viewsLoadError && (
                <LemonButton
                    size="small"
                    type="secondary"
                    status="danger"
                    onClick={loadViews}
                    loading={viewsLoading}
                    data-attr="account-notes-retry-views"
                >
                    Couldn't load views. Retry
                </LemonButton>
            )}
            <LemonMenu items={menuItems} closeOnClickInside>
                <LemonButton
                    type="secondary"
                    size="small"
                    sideIcon={<IconChevronDown />}
                    icon={currentView ? <ViewVisibilityIcon view={currentView} /> : undefined}
                    data-attr="account-notes-select-view"
                >
                    {currentView?.name ?? 'All notes'}
                </LemonButton>
            </LemonMenu>
            {!currentView && (
                <LemonButton
                    icon={<IconPlus />}
                    size="small"
                    type="secondary"
                    onClick={() => setIsCreating(true)}
                    data-attr="account-notes-save-view"
                >
                    Save view
                </LemonButton>
            )}
            {currentView && canEditCurrentView && (
                <>
                    {isDirty && (
                        <LemonButton
                            size="small"
                            type="secondary"
                            tooltip="Update this view with the current filters and ordering"
                            loading={viewsLoading}
                            onClick={() => updateView({ id: currentView.id, updates: {} })}
                            data-attr="account-notes-update-view"
                        >
                            Update "{currentView.name}"
                        </LemonButton>
                    )}
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconPencil />}
                        tooltip="Rename or change visibility"
                        onClick={() => setViewToEdit(currentView.id)}
                        data-attr="account-notes-edit-view"
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Delete view"
                        onClick={() => setViewToDelete(currentView.id)}
                        data-attr="account-notes-delete-view"
                    />
                </>
            )}
            <ViewModal logicProps={logicProps} />
            <DeleteViewModal logicProps={logicProps} />
        </div>
    )
}

function ViewModal({ logicProps }: { logicProps: AccountNotesViewsLogicProps }): JSX.Element {
    const logic = accountNotesViewsLogic(logicProps)
    const { isCreating, viewToEdit, isViewFormSubmitting, viewsLoading } = useValues(logic)
    const { submitViewForm, resetViewForm, setIsCreating, setViewToEdit } = useActions(logic)
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
            description={isEditing ? undefined : 'Save the current filters and ordering as a reusable view'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={close}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitViewForm}
                        loading={isSaving}
                        disabledReason={isSaving ? 'Saving...' : undefined}
                    >
                        {isEditing ? 'Save changes' : 'Save view'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={accountNotesViewsLogic} props={logicProps} formKey="viewForm">
                <div className="space-y-4">
                    <LemonField name="name" label="View name">
                        <LemonInput
                            placeholder="e.g. Renewal risks"
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

function DeleteViewModal({ logicProps }: { logicProps: AccountNotesViewsLogicProps }): JSX.Element {
    const logic = accountNotesViewsLogic(logicProps)
    const { views, viewToDelete, viewsLoading } = useValues(logic)
    const { deleteView, setViewToDelete } = useActions(logic)
    const view = views.find((candidate) => candidate.id === viewToDelete)

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
                        disabledReason={viewsLoading ? 'Deleting...' : undefined}
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
