import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconChevronDown, IconDownload, IconGear, IconPerson, IconPlus } from '@posthog/icons'
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

import { TableViewSupportedQueryType, tableViewLogic } from './tableViewLogic'

export interface TableViewSelectorProps {
    contextKey: string
    query: TableViewSupportedQueryType
    setQuery: (query: TableViewSupportedQueryType) => void
}

export function TableViewSelector({ contextKey, query, setQuery }: TableViewSelectorProps): JSX.Element {
    const tableViewLogicProps = { contextKey, query, setQuery }
    const logic = tableViewLogic(tableViewLogicProps)
    const { views, currentView, hasUnsavedChanges, viewsLoading, canEditCurrentView, user } = useValues(logic)
    const { applyView, updateView, setShowDeleteConfirm, setIsCreating } = useActions(logic)

    const menuItems: LemonMenuItems = [
        {
            items: views.map((view) => {
                const canEditView = view.created_by === user?.id
                return {
                    label: view.name,
                    icon:
                        view.visibility === 'private' ? (
                            <Tooltip title="This view is private. Only you can see and use it.">
                                <IconPerson className="text-muted" />
                            </Tooltip>
                        ) : undefined,
                    active: currentView?.id === view.id,
                    onClick: () => applyView(view),
                    ...(canEditView && {
                        sideAction: {
                            icon: <IconGear />,
                            tooltip: 'Manage view',
                            dropdown: {
                                overlay: (
                                    <>
                                        <LemonButton
                                            size="small"
                                            fullWidth
                                            onClick={() => {
                                                const newName = prompt('Rename view', view.name)
                                                if (newName && newName !== view.name) {
                                                    updateView(view.id, { name: newName })
                                                }
                                            }}
                                        >
                                            Rename
                                        </LemonButton>
                                        <LemonButton
                                            size="small"
                                            fullWidth
                                            status="danger"
                                            onClick={() => {
                                                setShowDeleteConfirm(view.id)
                                            }}
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
            items: [
                {
                    label: 'Create new view...',
                    icon: <IconPlus />,
                    onClick: () => setIsCreating(true),
                },
            ],
        },
    ]

    return (
        <BindLogic logic={tableViewLogic} props={tableViewLogicProps}>
            <div className="flex items-center gap-2">
                {currentView ? (
                    <LemonMenu items={menuItems} closeOnClickInside={true}>
                        <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                            {currentView?.name || 'Select view'}
                        </LemonButton>
                    </LemonMenu>
                ) : (
                    <LemonButton
                        icon={<IconDownload />}
                        size="small"
                        type="secondary"
                        onClick={() => setIsCreating(true)}
                    >
                        Save current view
                    </LemonButton>
                )}

                {currentView && hasUnsavedChanges && (
                    <LemonButton
                        icon={<IconDownload />}
                        size="small"
                        type="secondary"
                        tooltip="Update current view with changes"
                        disabledReason={!canEditCurrentView ? 'You can only edit views you created' : undefined}
                        loading={viewsLoading}
                        onClick={() => {
                            // Empty object triggers update with current state
                            updateView(currentView.id, {})
                        }}
                    >
                        Update "{currentView.name}"
                    </LemonButton>
                )}
            </div>

            <CreateViewModal />
            <DeleteConfirmationModal />
        </BindLogic>
    )
}

function CreateViewModal(): JSX.Element {
    const { isCreating, isNewViewFormSubmitting } = useValues(tableViewLogic)
    const { submitNewViewForm, resetNewViewForm, setIsCreating } = useActions(tableViewLogic)

    return (
        <LemonModal
            isOpen={isCreating}
            onClose={() => {
                setIsCreating(false)
                resetNewViewForm()
            }}
            title="Create new view"
            description="Save the current table configuration as a reusable view"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            setIsCreating(false)
                            resetNewViewForm()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitNewViewForm}
                        loading={isNewViewFormSubmitting}
                        disabledReason={isNewViewFormSubmitting ? 'Creating view...' : undefined}
                    >
                        Create view
                    </LemonButton>
                </>
            }
        >
            <Form logic={tableViewLogic} formKey="newViewForm">
                <div className="space-y-4">
                    <LemonField name="name" label="View name">
                        <LemonInput placeholder="View name" autoFocus onPressEnter={submitNewViewForm} />
                    </LemonField>
                    <LemonField name="visibility" label="Visibility">
                        <LemonSegmentedButton
                            options={[
                                { value: 'private', label: 'Private (only visible to me)' },
                                { value: 'shared', label: 'Shared with team' },
                            ]}
                            fullWidth
                        />
                    </LemonField>
                </div>
            </Form>
        </LemonModal>
    )
}

function DeleteConfirmationModal(): JSX.Element {
    const { views, showDeleteConfirm } = useValues(tableViewLogic)
    const { deleteView, setShowDeleteConfirm } = useActions(tableViewLogic)

    return (
        <LemonModal
            isOpen={!!showDeleteConfirm}
            onClose={() => setShowDeleteConfirm(null)}
            title="Delete view"
            description={`Are you sure you want to delete the view "${views.find((v) => v.id === showDeleteConfirm)?.name}"?`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setShowDeleteConfirm(null)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        onClick={() => {
                            if (showDeleteConfirm) {
                                deleteView(showDeleteConfirm)
                                setShowDeleteConfirm(null)
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
