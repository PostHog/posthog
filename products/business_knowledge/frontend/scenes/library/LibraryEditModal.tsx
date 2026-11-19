import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { LibraryNameForm } from '../libraries/LibraryNameForm'
import { knowledgeLibraryLogic } from './knowledgeLibraryLogic'
import { LibraryRepoForm } from './LibraryRepoForm'

export function LibraryEditModal(): JSX.Element | null {
    const { dialog, library, saving } = useValues(knowledgeLibraryLogic)
    const { closeDialog, renameLibrary, saveRepos } = useActions(knowledgeLibraryLogic)

    if (!dialog || !library) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={closeDialog}
            // Closing does not cancel the request, so a reopened modal could submit twice.
            closable={!saving}
            title={dialog === 'rename' ? 'Rename library' : `Repositories in ${library.name}`}
            description={
                dialog === 'repos'
                    ? 'Searching this library reads only these repositories. Choose from the repositories selected in settings.'
                    : undefined
            }
            width={480}
            footer={null}
        >
            {dialog === 'repos' ? (
                <LibraryRepoForm
                    initialRepos={library.repos}
                    saving={saving}
                    onCancel={closeDialog}
                    onSave={saveRepos}
                />
            ) : (
                <LibraryNameForm
                    initialName={library.name}
                    saving={saving}
                    submitLabel="Save"
                    onCancel={closeDialog}
                    onSubmit={renameLibrary}
                />
            )}
        </LemonModal>
    )
}
