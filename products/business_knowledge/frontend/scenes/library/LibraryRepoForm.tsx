import { useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { githubReposLogic } from '../settings/githubReposLogic'

export function LibraryRepoForm({
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
