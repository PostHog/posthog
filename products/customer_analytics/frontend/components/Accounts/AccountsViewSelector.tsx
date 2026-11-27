import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { SavedViewDeleteModal } from '../SavedViews/SavedViewDeleteModal'
import { SavedViewFormModal } from '../SavedViews/SavedViewFormModal'
import { SavedViewSelector } from '../SavedViews/SavedViewSelector'
import { accountsViewsLogic } from './accountsViewsLogic'

export function AccountsViewSelector(): JSX.Element {
    const {
        views,
        currentView,
        currentViewId,
        currentViewName,
        isDirty,
        viewsLoading,
        viewsLoaded,
        viewsLoadError,
        awaitingSavedView,
        isCreating,
        viewToEdit,
        viewToDelete,
        isViewFormSubmitting,
    } = useValues(accountsViewsLogic)
    const {
        selectView,
        updateView,
        setViewToDelete,
        setViewToEdit,
        setIsCreating,
        loadViews,
        submitViewForm,
        resetViewForm,
        deleteView,
    } = useActions(accountsViewsLogic)

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
                currentViewName={currentViewName}
                isDirty={isDirty}
                viewsLoading={viewsLoading}
                viewsLoaded={viewsLoaded}
                viewsLoadError={viewsLoadError}
                awaitingSavedView={awaitingSavedView}
                onSelect={selectView}
                onUpdate={(id) => updateView({ id, updates: {} })}
                onEdit={setViewToEdit}
                onDelete={setViewToDelete}
                onCreate={() => setIsCreating(true)}
                onRetry={loadViews}
                dataAttrPrefix="accounts"
            />
            <SavedViewFormModal
                isOpen={isCreating || !!viewToEdit}
                isEditing={!!viewToEdit}
                isSaving={isViewFormSubmitting || viewsLoading}
                description="Save the current filters, columns, ordering, and overview tiles as a reusable view"
                placeholder="e.g. Enterprise accounts"
                onClose={closeForm}
                onSubmit={submitViewForm}
                renderForm={(fields) => (
                    <Form logic={accountsViewsLogic} formKey="viewForm">
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
