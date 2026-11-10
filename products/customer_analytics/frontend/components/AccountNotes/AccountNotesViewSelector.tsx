import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { membersLogic } from '~/models/membersLogic'

import { SavedViewDeleteModal } from '../SavedViews/SavedViewDeleteModal'
import { SavedViewFormModal } from '../SavedViews/SavedViewFormModal'
import { SavedViewSelector } from '../SavedViews/SavedViewSelector'
import {
    AccountNotesViewsLogicProps,
    accountNotesViewsLogic,
    deserializeAccountNotesView,
} from './accountNotesViewsLogic'
import { AccountNotesViewSummary } from './AccountNotesViewSummary'

interface AccountNotesViewSelectorProps {
    logicProps?: AccountNotesViewsLogicProps
}

export function AccountNotesViewSelector({ logicProps = {} }: AccountNotesViewSelectorProps): JSX.Element {
    const logic = accountNotesViewsLogic(logicProps)
    const {
        views,
        currentView,
        currentViewId,
        isDirty,
        viewsLoading,
        viewsLoaded,
        viewsLoadError,
        isCreating,
        viewToEdit,
        viewToDelete,
        isViewFormSubmitting,
    } = useValues(logic)
    const {
        selectView,
        clearView,
        updateView,
        setViewToDelete,
        setViewToEdit,
        setIsCreating,
        loadViews,
        submitViewForm,
        resetViewForm,
        deleteView,
    } = useActions(logic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    const closeForm = (): void => {
        setIsCreating(false)
        setViewToEdit(null)
        resetViewForm()
    }

    return (
        <>
            <SavedViewSelector
                views={views}
                currentView={currentView}
                currentViewId={currentViewId}
                isDirty={isDirty}
                viewsLoading={viewsLoading}
                viewsLoaded={viewsLoaded}
                viewsLoadError={viewsLoadError}
                onSelect={selectView}
                resetOption={{ label: 'All notes', onClick: clearView }}
                onUpdate={(id) => updateView({ id, updates: {} })}
                onEdit={setViewToEdit}
                onDelete={setViewToDelete}
                onCreate={() => setIsCreating(true)}
                onRetry={loadViews}
                onVisibilityChange={(open) => {
                    if (open) {
                        ensureAllMembersLoaded()
                    }
                }}
                renderViewTooltip={(view) => (
                    <AccountNotesViewSummary
                        state={deserializeAccountNotesView(view)}
                        scope={logicProps.sourceLogic ? 'account' : 'notes_tab'}
                    />
                )}
                dataAttrPrefix="account-notes"
            />
            <SavedViewFormModal
                isOpen={isCreating || !!viewToEdit}
                isEditing={!!viewToEdit}
                isSaving={isViewFormSubmitting || viewsLoading}
                description="Save the current filters and sorting as a reusable view"
                placeholder="e.g. Renewal risks"
                onClose={closeForm}
                onSubmit={submitViewForm}
                renderForm={(fields) => (
                    <Form logic={accountNotesViewsLogic} props={logicProps} formKey="viewForm">
                        {fields}
                    </Form>
                )}
            />
            <SavedViewDeleteModal
                isOpen={!!viewToDelete}
                name={views.find((view) => view.id === viewToDelete)?.name}
                isDeleting={viewsLoading}
                onClose={() => setViewToDelete(null)}
                onDelete={() => {
                    if (viewToDelete) {
                        deleteView({ id: viewToDelete })
                    }
                }}
            />
        </>
    )
}
