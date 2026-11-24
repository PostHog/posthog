import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { librariesLogic } from './librariesLogic'
import { LibraryNameForm } from './LibraryNameForm'

export function LibraryCreateModal(): JSX.Element | null {
    const { isCreateOpen, creating } = useValues(librariesLogic)
    const { closeCreate, createLibrary } = useActions(librariesLogic)

    if (!isCreateOpen) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={closeCreate}
            // Closing does not cancel the request, so a reopened modal could submit twice.
            closable={!creating}
            title="New library"
            description="A library groups sources and repositories. An agent key for a library reads only what is in it."
            width={480}
            footer={null}
        >
            <LibraryNameForm
                initialName=""
                saving={creating}
                submitLabel="Create library"
                onCancel={closeCreate}
                onSubmit={createLibrary}
            />
        </LemonModal>
    )
}
