import { router } from 'kea-router'

import { Button } from '@posthog/quill'

import { urls } from 'scenes/urls'

export function QuillActionEditActions({
    isNew,
    saving,
    actionChanged,
    saveDisabledReason,
    onSave,
}: {
    isNew: boolean
    saving: boolean
    actionChanged: boolean
    saveDisabledReason: string | undefined
    onSave: () => void
}): JSX.Element {
    return (
        <>
            {isNew && (
                <Button
                    data-attr="cancel-action-bottom"
                    variant="destructive-outline"
                    onClick={() => router.actions.push(urls.actions())}
                    tooltip="Cancel and return to the list of actions"
                >
                    Cancel
                </Button>
            )}
            <Button
                data-attr="save-action-button"
                variant="primary"
                type="submit"
                loading={saving}
                onClick={(e) => {
                    e.preventDefault()
                    onSave()
                }}
                disabledReason={saveDisabledReason}
            >
                {actionChanged ? 'Save' : 'No changes'}
            </Button>
        </>
    )
}
