import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonInputSelect, LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { githubReposLogic } from '../settings/githubReposLogic'
import { businessKnowledgeLogic } from './businessKnowledgeLogic'

export function LibraryDialog(): JSX.Element | null {
    const githubEnabled = useFeatureFlag('BUSINESS_KNOWLEDGE_GITHUB_REPOS')
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
            {libraryDialog === 'repos' && githubEnabled && active ? (
                <RepoForm
                    initialRepos={active.repos}
                    saving={savingLibrary}
                    onCancel={closeLibraryDialog}
                    onSave={saveLibraryRepos}
                />
            ) : (
                <NameForm
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

function NameForm({
    initialName,
    saving,
    submitLabel,
    onCancel,
    onSubmit,
}: {
    initialName: string
    saving: boolean
    submitLabel: string
    onCancel: () => void
    onSubmit: (name: string) => void
}): JSX.Element {
    const [name, setName] = useState(initialName)
    return (
        <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
                event.preventDefault()
                if (!name.trim() || saving) {
                    return
                }
                onSubmit(name.trim())
            }}
        >
            <LemonInput value={name} onChange={setName} placeholder="Library name" autoFocus />
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={onCancel} disabledReason={saving ? 'Saving' : undefined}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={saving}
                    disabledReason={!name.trim() ? 'Enter a name' : undefined}
                >
                    {submitLabel}
                </LemonButton>
            </div>
        </form>
    )
}

function RepoForm({
    initialRepos,
    saving,
    onCancel,
    onSave,
}: {
    initialRepos: string[]
    saving: boolean
    onCancel: () => void
    onSave: (repos: string[]) => void
}): JSX.Element {
    useMountedLogic(githubReposLogic)
    const { connection, connectionLoading } = useValues(githubReposLogic)
    const [repos, setRepos] = useState(initialRepos)
    const options = (connection?.repos ?? []).map((repo) => ({ key: repo, label: repo }))
    return (
        <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
                event.preventDefault()
                if (saving) {
                    return
                }
                onSave(repos)
            }}
        >
            {connectionLoading && !connection ? (
                <p className="m-0 text-muted">Loading repositories…</p>
            ) : options.length === 0 ? (
                <p className="m-0">Select repositories in business knowledge settings before adding them here.</p>
            ) : (
                <LemonInputSelect
                    mode="multiple"
                    value={repos}
                    options={options}
                    onChange={setRepos}
                    placeholder="Choose repositories"
                />
            )}
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={onCancel} disabledReason={saving ? 'Saving' : undefined}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={saving}
                    disabledReason={options.length === 0 ? 'No repositories selected' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </form>
    )
}
