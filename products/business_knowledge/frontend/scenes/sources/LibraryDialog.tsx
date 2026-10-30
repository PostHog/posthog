import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { businessKnowledgeLogic } from './businessKnowledgeLogic'
import { LibraryNameForm } from './LibraryNameForm'
import { LibraryRepoForm } from './LibraryRepoForm'

export function LibraryDialog(): JSX.Element | null {
    const { libraryDialog, libraryScope, libraries, savingLibrary } = useValues(businessKnowledgeLogic)
    const { closeLibraryDialog, createLibrary, renameLibrary, saveLibraryRepos } = useActions(businessKnowledgeLogic)
    const active = libraries.find((library) => library.id === libraryScope)

    if (!libraryDialog) {
        return null
    }
    if (libraryDialog !== 'create' && !active) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={closeLibraryDialog}
            // Closing resets the saving state without cancelling the request, so a reopened dialog could submit twice.
            closable={!savingLibrary}
            title={
                libraryDialog === 'create'
                    ? 'New library'
                    : libraryDialog === 'rename'
                      ? 'Rename library'
                      : `Repositories in ${active?.name ?? 'this library'}`
            }
            description={
                libraryDialog === 'create'
                    ? 'A library groups sources and repositories. Add sources to it from a source page or when you add a new source.'
                    : libraryDialog === 'repos'
                      ? 'Searching this library reads only these repositories. Choose from the repositories selected in settings.'
                      : undefined
            }
            width={480}
            footer={null}
        >
            {libraryDialog === 'repos' && active ? (
                <LibraryRepoForm
                    initialRepos={active.repos}
                    saving={savingLibrary}
                    onCancel={closeLibraryDialog}
                    onSave={saveLibraryRepos}
                />
            ) : (
                <LibraryNameForm
                    initialName={libraryDialog === 'rename' && active ? active.name : ''}
                    saving={savingLibrary}
                    submitLabel={libraryDialog === 'create' ? 'Create library' : 'Save'}
                    onCancel={closeLibraryDialog}
                    onSubmit={(name) => (libraryDialog === 'create' ? createLibrary(name) : renameLibrary(name))}
                />
            )}
        </LemonModal>
    )
}
