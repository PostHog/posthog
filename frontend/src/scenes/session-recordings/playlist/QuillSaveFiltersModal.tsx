import { useActions } from 'kea'
import { useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
} from '@posthog/quill'

import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'

import { RecordingUniversalFilters } from '~/types'

import { createPlaylist, stripSessionIds } from './playlistUtils'

export function QuillSaveFiltersModal({
    isOpen,
    setIsOpen,
    filters,
}: {
    isOpen: boolean
    setIsOpen: (open: boolean) => void
    filters: RecordingUniversalFilters
}): JSX.Element {
    const { loadSavedFilters, setAppliedSavedFilter } = useActions(sessionRecordingSavedFiltersLogic)
    const [name, setName] = useState('')

    const close = (): void => {
        setIsOpen(false)
        setName('')
    }

    const save = async (): Promise<void> => {
        const saved = await createPlaylist(
            { name, filters: stripSessionIds(filters), type: 'filters', creation_method: 'new' },
            false
        )
        loadSavedFilters()
        close()
        setAppliedSavedFilter(saved)
    }

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Save filters for later</DialogTitle>
                    <DialogDescription>You can access them from the saved filters menu</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <Input
                        value={name}
                        placeholder="Saved filter name"
                        autoFocus
                        onChange={(event) => setName(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter' && name.length > 0) {
                                void save()
                            }
                        }}
                        data-attr="filters-save-modal-name"
                    />
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={close} data-attr="filters-save-modal-close">
                        Close
                    </Button>
                    <Button
                        variant="primary"
                        disabledReason={name.length === 0 ? 'Enter a name' : undefined}
                        onClick={() => void save()}
                        data-attr="filters-save-modal-save"
                    >
                        Save filters
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
