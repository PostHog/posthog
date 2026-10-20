import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { todayAnalyticsLogic } from './todayAnalyticsLogic'

/** Asks for a name and creates a top-level project folder. */
export function TodayAnalyticsNewFolderDialog(): JSX.Element {
    const { newFolderDialogOpen, creatingFolder, newFolderParent } = useValues(todayAnalyticsLogic)
    const { setNewFolderDialogOpen, createFolder } = useActions(todayAnalyticsLogic)
    const [name, setName] = useState('')
    const trimmed = name.trim()

    return (
        <Dialog
            open={newFolderDialogOpen}
            onOpenChange={(open: boolean) => {
                setNewFolderDialogOpen(open)
                if (!open) {
                    setName('')
                }
            }}
        >
            <DialogContent data-attr="analytics-new-folder-dialog">
                <form
                    className="contents"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (trimmed && !creatingFolder) {
                            createFolder(trimmed)
                        }
                    }}
                >
                    <DialogHeader>
                        <DialogTitle>
                            {newFolderParent ? `New folder in ${newFolderParent}` : 'New collection'}
                        </DialogTitle>
                        <DialogDescription>
                            {newFolderParent
                                ? 'A folder inside this collection.'
                                : 'A collection for a team or an area. Add dashboards, insights, notebooks and canvases to it from their own pages.'}
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        <Field>
                            <FieldLabel htmlFor="analytics-new-folder-name">Name</FieldLabel>
                            <Input
                                id="analytics-new-folder-name"
                                autoFocus
                                value={name}
                                onChange={(event: React.ChangeEvent<HTMLInputElement>) => setName(event.target.value)}
                                placeholder={newFolderParent ? 'Q4 launch' : 'Growth team'}
                                data-attr="analytics-new-folder-name"
                            />
                        </Field>
                    </DialogBody>
                    <DialogFooter>
                        <DialogClose render={<Button variant="outline" data-attr="analytics-new-folder-cancel" />}>
                            Cancel
                        </DialogClose>
                        <Button
                            type="submit"
                            variant="primary"
                            loading={creatingFolder}
                            disabled={!trimmed}
                            data-attr="analytics-new-folder-create"
                        >
                            {newFolderParent ? 'Create folder' : 'Create collection'}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    )
}
