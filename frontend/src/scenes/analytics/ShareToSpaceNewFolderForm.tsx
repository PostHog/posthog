import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Card, Field, FieldLabel, Input } from '@posthog/quill'

import { analyticsShareLogic } from './analyticsShareLogic'

/** Names a new folder in the open collection, or a new collection at the top of the picker. */
export function ShareToSpaceNewFolderForm(): JSX.Element {
    const { browsePath, newFolderName, creatingFolder } = useValues(analyticsShareLogic)
    const { setNewFolderOpen, setNewFolderName, createFolder } = useActions(analyticsShareLogic)
    const atRoot = browsePath === null
    const cancelLabel = atRoot ? 'Cancel new collection' : 'Cancel new folder'

    return (
        <Card size="sm" className="relative mb-2 p-3">
            <Button
                size="icon-xs"
                className="absolute top-1.5 right-1.5"
                aria-label={cancelLabel}
                tooltip={cancelLabel}
                onClick={() => setNewFolderOpen(false)}
                data-attr="analytics-share-new-folder-cancel"
            >
                <IconX />
            </Button>
            <form
                className="flex items-end gap-2"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (newFolderName.trim() && !creatingFolder) {
                        createFolder()
                    }
                }}
            >
                <Field className="flex-1">
                    <FieldLabel htmlFor="analytics-share-new-folder-name">
                        {atRoot ? 'Collection name' : 'Folder name'}
                    </FieldLabel>
                    <Input
                        id="analytics-share-new-folder-name"
                        autoFocus
                        placeholder={atRoot ? 'Growth team' : 'Q4 launch'}
                        value={newFolderName}
                        onChange={(event: React.ChangeEvent<HTMLInputElement>) => setNewFolderName(event.target.value)}
                        onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                            if (event.key === 'Escape') {
                                event.preventDefault()
                                event.stopPropagation()
                                setNewFolderOpen(false)
                            }
                        }}
                        data-attr="analytics-share-new-folder-name"
                    />
                </Field>
                <Button
                    type="submit"
                    variant="outline"
                    loading={creatingFolder}
                    disabledReason={newFolderName.trim() ? undefined : 'Enter a name'}
                    data-attr="analytics-share-new-folder-create"
                >
                    Create
                </Button>
            </form>
        </Card>
    )
}
