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
import { fullName } from 'lib/utils/strings'

import { membersLogic } from '~/models/membersLogic'

import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import type { AccountNotesViewState } from './accountNotesLogic'
import {
    AccountNotesViewsLogicProps,
    accountNotesViewsLogic,
    describeAccountNotesView,
    deserializeAccountNotesView,
} from './accountNotesViewsLogic'

interface AccountNotesViewSelectorProps {
    logicProps?: AccountNotesViewsLogicProps
}

type ViewScope = 'notes_tab' | 'account'

function useMemberName(): (userId: number) => string {
    const { meFirstMembers } = useValues(membersLogic)
    return (userId: number): string => {
        const member = meFirstMembers.find((candidate) => candidate.user.id === userId)
        return member ? fullName(member.user) || member.user.email : `user ${userId}`
    }
}

// The plain list of what a view saves, so nobody has to guess what clicking it will do.
function ViewSummary({ state, scope }: { state: AccountNotesViewState; scope: ViewScope }): JSX.Element {
    const memberName = useMemberName()
    const { applied, teamTabOnly } = describeAccountNotesView(state, memberName, scope)
    return (
        <div className="space-y-1" data-attr="account-notes-view-summary">
            <ul className="list-disc pl-4 space-y-0.5">
                {applied.map((line) => (
                    <li key={line}>{line}</li>
                ))}
            </ul>
            {teamTabOnly.length > 0 && (
                <div className="text-secondary text-xs">
                    Applies on the team Notes tab only: {teamTabOnly.join(', ')}
                </div>
            )}
        </div>
    )
}

export function AccountNotesViewSelector({ logicProps = {} }: AccountNotesViewSelectorProps): JSX.Element {
    const logic = accountNotesViewsLogic(logicProps)
    const { views, currentView, isDirty, canEditCurrentView, viewsLoading, viewsLoadError } = useValues(logic)
    const { selectView, clearView, updateView, setViewToDelete, setViewToEdit, setIsCreating, loadViews } =
        useActions(logic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const scope: ViewScope = logicProps.sourceLogic ? 'account' : 'notes_tab'

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
                            tooltip: <ViewSummary state={deserializeAccountNotesView(view)} scope={scope} />,
                            tooltipPlacement: 'right',
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
            <LemonMenu
                items={menuItems}
                closeOnClickInside
                onVisibilityChange={(open) => open && ensureAllMembersLoaded()}
            >
                <LemonButton
                    type="secondary"
                    size="small"
                    sideIcon={<IconChevronDown />}
                    icon={currentView ? <ViewVisibilityIcon view={currentView} /> : undefined}
                    tooltip={
                        currentView ? (
                            <ViewSummary state={deserializeAccountNotesView(currentView)} scope={scope} />
                        ) : undefined
                    }
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
    const { isCreating, viewToEdit, isViewFormSubmitting, viewsLoading, viewState, views } = useValues(logic)
    const { submitViewForm, resetViewForm, setIsCreating, setViewToEdit } = useActions(logic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const isEditing = !!viewToEdit
    const isSaving = isViewFormSubmitting || viewsLoading
    const scope: ViewScope = logicProps.sourceLogic ? 'account' : 'notes_tab'
    const editedView = isEditing ? views.find((view) => view.id === viewToEdit) : undefined
    // Creating saves what is on screen now; editing changes only the name and visibility, so show the saved contents.
    const savedState = editedView ? deserializeAccountNotesView(editedView) : viewState

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
                    ? 'Rename the view or change who sees it. To change what it shows, apply it, adjust the filters and click Update.'
                    : 'A view saves the filters and sort you have on screen now, so you can come back to them in one click.'
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
                        disabledReason={isSaving ? 'Saving...' : undefined}
                    >
                        {isEditing ? 'Save changes' : 'Save view'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={accountNotesViewsLogic} props={logicProps} formKey="viewForm">
                <div className="space-y-4" onFocus={() => ensureAllMembersLoaded()}>
                    <div>
                        <div className="font-semibold mb-1">
                            {isEditing ? 'This view shows' : 'This view will save'}
                        </div>
                        <ViewSummary state={savedState} scope={scope} />
                    </div>
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
