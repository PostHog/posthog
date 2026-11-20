import { Button } from '@posthog/quill'

import { AlertEditorActionsProps } from './AlertEditor'

export function QuillAlertEditorActions({
    isEditing,
    isSubmitting,
    hasChanges,
    hasPendingChanges = false,
    leadingActions,
    trailingActions,
    onSubmitAttempted,
    showNoChangesLabel = false,
    noChangesReason = 'No changes to save',
}: AlertEditorActionsProps): JSX.Element {
    const hasUnsavedChanges = hasChanges || hasPendingChanges
    const disabledReason = isEditing && !hasUnsavedChanges ? noChangesReason : undefined
    let buttonLabel = 'Create alert'
    if (isEditing) {
        buttonLabel = showNoChangesLabel && !hasUnsavedChanges ? 'No changes' : 'Save'
    }

    return (
        <>
            {leadingActions ? <div className="w-full sm:min-w-0 sm:flex-1">{leadingActions}</div> : null}
            <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto">
                {trailingActions}
                <Button
                    variant="primary"
                    type="submit"
                    loading={isSubmitting}
                    disabledReason={disabledReason}
                    onClick={onSubmitAttempted}
                >
                    {buttonLabel}
                </Button>
            </div>
        </>
    )
}
